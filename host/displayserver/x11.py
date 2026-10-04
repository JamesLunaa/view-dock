# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""X11 implementation of DisplayServer.

Virtual output is created via `xrandr` (dummy output / `--addmode`); frames
are captured via `mss`. This is the phase 1 implementation (X11 first,
Wayland later).

Requires a spare output already present in the X server — either a
genuinely disconnected one backed by `xorg-dummy` (aka `xf86-video-dummy`),
or a real GPU output forced on at the kernel/DRM level (see host/README.md's
"Real GPU output, no dummy driver" section for how and why — in short,
`xrandr`-level forcing alone isn't always accepted by the driver, and even
when it is, desktop environments' own display-management layers like KDE's
kscreen won't treat it as a real screen for window placement without a
genuine DRM-level connection). Either way, what this code actually looks
for is "has no active mode right now" — not the connected/disconnected word,
since a kernel-forced output reports "connected" with no geometry until a
mode is set, same shape as a genuinely disconnected one.
"""

import logging
import os
import re
import subprocess
import time

import numpy as np
import mss

from host.config import DisplayConfig
from host.displayserver.base import DisplayServer
from host.displayserver.connector import force_connector, unforce_connector
from host.displayserver.cursor import X11CursorCompositor
from host.displayserver.geometry_watch import ScreenLayoutWatcher

logger = logging.getLogger(__name__)

_OUTPUT_STATUS_RE = re.compile(r"^(\S+) (?:dis)?connected\b(.*)$")
_GEOMETRY_RE = re.compile(r"\d+x\d+\+\d+\+\d+")
_PRIMARY_RE = re.compile(r"^(\S+) connected primary")
_STALE_MODE_RE = re.compile(r"^\s+(viewdock_\S+)")
# The cursor query can fail transiently (seen: a one-off XFixes BadAccess
# right after a display rearrangement), so only give up on the overlay once
# it has failed this many frames in a row (~2 s at 60 fps).
_CURSOR_MAX_CONSECUTIVE_FAILURES = 120
_AUTO_HANDOFF = os.environ.get("VIEWDOCK_AUTO_HANDOFF") == "1"
_HANDOFF_SETTLE_S = 3.0
_DISCONNECTED_RE = re.compile(r"^(\S+) disconnected\b")


def _spare_rank(name: str) -> tuple[int, int]:
    """Sort key for choosing which disconnected output to force: the one a
    user is least likely to plug a real monitor into. HDMI is the port people
    actually use, so it goes last; among the rest, higher-numbered DP outputs
    (typically unpopulated or dock-only) go first."""
    m = re.search(r"(\d+)$", name)
    index = int(m.group(1)) if m else 0
    return (name.startswith("HDMI"), -index)


class X11DisplayServer(DisplayServer):
    def __init__(self) -> None:
        self._output_name: str | None = None
        self._mode_name: str | None = None
        self._sct: mss.base.MSSBase | None = None
        self._monitor: dict[str, int] | None = None
        self._cursor: X11CursorCompositor | None = None
        self._cursor_failures = 0
        self._layout_watcher: ScreenLayoutWatcher | None = None
        self._last_monitor_check = 0.0
        self._warned_real_monitor = False
        self._config: DisplayConfig | None = None
        self._forced_output: str | None = None
        self._handoff_at: float | None = None

    def create_virtual_display(self, config: DisplayConfig) -> None:
        output = self.ensure_spare_output()
        if output is None:
            raise RuntimeError(
                "No spare output available for the virtual display. Configure a "
                "dummy output (xf86-video-dummy) or force a real GPU output on at "
                "the kernel/DRM level — see host/README.md."
            )

        self._config = config
        self._enable_on(output, config)
        self._sct = mss.mss()
        self._monitor = self._find_monitor_geometry(output)

        try:
            self._cursor = X11CursorCompositor()
            self._cursor_failures = 0
        except Exception:
            # Cosmetic feature — a display without XFixes should still stream.
            logger.warning("Cursor overlay unavailable; streaming without it.", exc_info=True)
            self._cursor = None

        try:
            self._layout_watcher = ScreenLayoutWatcher()
        except Exception:
            logger.warning(
                "Screen layout watcher unavailable; the captured region will not "
                "follow display rearrangement.",
                exc_info=True,
            )
            self._layout_watcher = None

    def _enable_on(self, output: str, config: DisplayConfig) -> None:
        mode_name, modeline = self._build_modeline(config)
        subprocess.run(["xrandr", "--newmode", mode_name, *modeline], check=True)
        subprocess.run(["xrandr", "--addmode", output, mode_name], check=True)

        enable_command = ["xrandr", "--output", output, "--mode", mode_name]
        # All outputs on one X screen share a single coordinate canvas — with
        # no position given, a new output defaults to 0,0, the same origin
        # as everything else, so it just captures whatever's already visible
        # there instead of being a genuinely separate extended area. Placing
        # it beside the real primary output (if there is one — the isolated
        # dummy-only test server in host/xorg/dummy.conf has none) makes this
        # an actual extended desktop: windows dragged into that region show
        # up here.
        primary = self._find_primary_output()
        if primary is not None and primary != output:
            enable_command += ["--right-of", primary]
        try:
            subprocess.run(enable_command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as error:
            # Don't leave the half-added mode behind (the connector stays
            # forced, but that is harmless and reused on the next start).
            subprocess.run(["xrandr", "--delmode", output, mode_name], check=False)
            subprocess.run(["xrandr", "--rmmode", mode_name], check=False)
            raise RuntimeError(
                f"xrandr could not enable {mode_name} on {output} "
                f"({(error.stderr or '').strip() or 'no error text'}). A forced "
                f"DisplayPort output often can't carry a high pixel clock (this mode "
                f"is {modeline[0]} MHz): try a smaller size via "
                "VIEWDOCK_DISPLAY_WIDTH/HEIGHT, or force an HDMI output instead "
                "(host/scripts/force-connector.sh HDMI-A-1)."
            ) from error

        self._output_name = output
        self._mode_name = mode_name

    @staticmethod
    def _output_has_real_monitor(output: str) -> bool:
        """True if a physical monitor reports itself on `output`. A bare forced
        connector reports `0mm x 0mm`; a real display's EDID gives its size."""
        result = subprocess.run(["xrandr", "--query"], check=True, capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if line.startswith(f"{output} "):
                m = re.search(r"(\d+)mm x (\d+)mm", line)
                return bool(m and int(m.group(1)) and int(m.group(2)))
        return False

    def _hand_off_to_real_monitor(self) -> None:
        """A real monitor now sits on the connector we forced. Give it back and
        move the virtual display to another spare output, then make sure at
        least one real display is still lit."""
        old = self._output_name
        logger.info("Real monitor on %s; moving the virtual display to another output.", old)
        try:
            subprocess.run(["xrandr", "--output", old, "--off"], check=False)
            subprocess.run(["xrandr", "--delmode", old, self._mode_name], check=False)
            subprocess.run(["xrandr", "--rmmode", self._mode_name], check=False)
            if self._forced_output == old:
                unforce_connector(old)
                self._forced_output = None
            time.sleep(_HANDOFF_SETTLE_S)  # kernel re-probe + kscreen reaction
            new = self.ensure_spare_output(exclude={old})
            if new is None:
                raise RuntimeError(f"A real monitor took {old} and no other spare output is available.")
            self._enable_on(new, self._config)
            self._monitor = self._find_monitor_geometry(new)
        finally:
            self._ensure_a_display_is_lit()

    def _ensure_a_display_is_lit(self) -> None:
        """Safety net: if no real output has geometry, let XRandR re-enable
        everything it can rather than leaving the user at a black screen."""
        result = subprocess.run(["xrandr", "--query"], check=True, capture_output=True, text=True)
        lit = [
            m.group(1)
            for line in result.stdout.splitlines()
            if (m := _OUTPUT_STATUS_RE.match(line)) and _GEOMETRY_RE.search(m.group(2))
            and m.group(1) != self._output_name
        ]
        if not lit:
            logger.error("No real display is lit after the handoff; running xrandr --auto.")
            subprocess.run(["xrandr", "--auto"], check=False)

    supports_bgra_capture = True

    def capture_frame(self) -> np.ndarray:
        shot = self._grab()
        # mss returns BGRA; drop alpha and reorder to RGB for the encoder.
        # Advanced indexing copies, so the result is safe to draw into below.
        frame = np.asarray(shot)[:, :, [2, 1, 0]]
        self._draw_cursor(frame, bgr=False)
        return frame

    def capture_frame_bgra(self) -> np.ndarray:
        """The frame exactly as X11 delivers it (BGRA), skipping the reorder copy
        `capture_frame` does — about 4 ms of a 16 ms frame budget at 60 fps."""
        shot = self._grab()
        frame = np.asarray(shot)  # a view of this grab's own buffer, not shared between frames
        if not frame.flags.writeable:
            frame = frame.copy()  # the cursor is drawn in place below
        self._draw_cursor(frame, bgr=True)
        return frame

    def _grab(self):
        if self._sct is None or self._monitor is None:
            raise RuntimeError("Virtual display not created; call create_virtual_display() first.")
        self._refresh_geometry_if_moved()
        return self._sct.grab(self._monitor)

    def _draw_cursor(self, frame: np.ndarray, bgr: bool) -> None:
        if self._cursor is not None:
            try:
                self._cursor.composite(frame, self._monitor, bgr=bgr)
                self._cursor_failures = 0
            except Exception:
                self._cursor_failures += 1
                if self._cursor_failures == 1:
                    logger.warning("Cursor overlay failed; skipping it this frame.", exc_info=True)
                if self._cursor_failures >= _CURSOR_MAX_CONSECUTIVE_FAILURES:
                    logger.warning(
                        "Cursor overlay failed %d frames in a row; disabling it.",
                        self._cursor_failures,
                    )
                    self._cursor.close()
                    self._cursor = None

    def _refresh_geometry_if_moved(self) -> None:
        """Re-resolve the capture rectangle after a display rearrangement.

        Only does real work when RandR says the layout changed, so the common
        case costs one non-blocking event-queue check per frame.
        """
        if self._layout_watcher is None or self._output_name is None:
            return
        changed = self._layout_watcher.layout_changed()
        now = time.monotonic()
        # `xrandr --query` costs ~75 ms here — several dropped frames if it ran
        # on a timer in the capture path — so only run it when RandR reports a
        # layout change, plus a 1 s poll while a handoff is waiting to settle.
        if changed or (self._handoff_at is not None and now - self._last_monitor_check > 1.0):
            self._last_monitor_check = now
            if self._output_has_real_monitor(self._output_name):
                if not _AUTO_HANDOFF:
                    if not self._warned_real_monitor:
                        self._warned_real_monitor = True
                        logger.warning(
                            "A real monitor was plugged into %s, which the virtual display is "
                            "using, so it will mirror the iPad. Set VIEWDOCK_AUTO_HANDOFF=1 to "
                            "move the virtual display automatically, or restart the host.",
                            self._output_name,
                        )
                elif self._handoff_at is None or changed:
                    # Debounce: let KDE's kscreen finish reacting to the
                    # hotplug before touching any output (touching them while
                    # it reconfigures blanked every screen, found live).
                    self._handoff_at = now + _HANDOFF_SETTLE_S
                elif now >= self._handoff_at:
                    self._handoff_at = None
                    self._hand_off_to_real_monitor()
                    return
            else:
                self._handoff_at = None
        if not changed:
            return

        try:
            moved = self._find_monitor_geometry(self._output_name)
        except RuntimeError:
            # The output can be momentarily absent mid-reconfiguration, and
            # the user may have disabled it outright. Keep the last known
            # rectangle; the next change event will resolve it again.
            logger.warning("Virtual output %s has no geometry right now.", self._output_name)
            return

        if moved != self._monitor:
            logger.info("Virtual display moved: %s -> %s", self._monitor, moved)
            self._monitor = moved

    def destroy_virtual_display(self) -> None:
        if self._output_name is None:
            return

        subprocess.run(["xrandr", "--output", self._output_name, "--off"], check=False)
        if self._mode_name is not None:
            subprocess.run(["xrandr", "--delmode", self._output_name, self._mode_name], check=False)
            subprocess.run(["xrandr", "--rmmode", self._mode_name], check=False)
        if self._sct is not None:
            self._sct.close()
        if self._cursor is not None:
            self._cursor.close()
        if self._layout_watcher is not None:
            self._layout_watcher.close()

        self._output_name = None
        self._mode_name = None
        self._sct = None
        self._monitor = None
        self._cursor = None
        self._layout_watcher = None

    @staticmethod
    def list_disconnected_outputs() -> list[str]:
        """Outputs XRandR currently reports as genuinely disconnected.

        For host/ui's "no spare output" message: these are candidates for
        `scripts/force-connector.sh`. Note that script wants the DRM
        connector name, which differs from this XRandR output name for the
        same port (e.g. `HDMI-A-1` vs `HDMI-1`) — see host/README.md's "Real
        GPU output on an Xorg desktop" section.
        """
        result = subprocess.run(["xrandr", "--query"], check=True, capture_output=True, text=True)
        return [m.group(1) for line in result.stdout.splitlines() if (m := _DISCONNECTED_RE.match(line))]

    @staticmethod
    def find_available_output(exclude: frozenset[str] | set[str] = frozenset()) -> str | None:
        """First output with no geometry, preferring one XRandR reports as
        connected (a forced connector or a dummy output) over a disconnected
        one, which KDE won't treat as a screen until it's forced."""
        free = [o for o in X11DisplayServer._free_outputs() if o[0] not in exclude]
        for name, connected in free:
            if connected:
                return name
        return free[0][0] if free else None

    @staticmethod
    def _free_outputs() -> list[tuple[str, bool]]:
        result = subprocess.run(["xrandr", "--query"], check=True, capture_output=True, text=True)
        free = []
        for line in result.stdout.splitlines():
            match = _OUTPUT_STATUS_RE.match(line)
            if match and not _GEOMETRY_RE.search(match.group(2)):
                free.append((match.group(1), not line.startswith(f"{match.group(1)} disconnected")))
        return free

    def ensure_spare_output(self, exclude: set[str] = frozenset()) -> str | None:
        """Like `find_available_output`, but if the only free outputs are
        disconnected, forces one on at the DRM level first (the per-boot step
        `scripts/force-connector.sh` used to be run by hand for)."""
        free = [o for o in X11DisplayServer._free_outputs() if o[0] not in exclude]
        if not free or any(connected for _, connected in free):
            return X11DisplayServer.find_available_output(exclude)

        for name in sorted((n for n, _ in free), key=_spare_rank):
            logger.info("No connected spare output; forcing %s on.", name)
            if force_connector(name) is None:
                continue
            self._forced_output = name
            # The kernel re-probes asynchronously; wait for XRandR to catch up.
            for _ in range(50):
                if any(n == name and connected for n, connected in self._free_outputs()):
                    return name
                time.sleep(0.1)
            logger.warning("%s did not come up after forcing; trying the next output.", name)
        return free[0][0]  # nothing could be forced: caller proceeds and may fail visibly

    @staticmethod
    def _find_primary_output() -> str | None:
        result = subprocess.run(["xrandr", "--query"], check=True, capture_output=True, text=True)
        for line in result.stdout.splitlines():
            match = _PRIMARY_RE.match(line)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def cleanup_stale_virtual_outputs() -> list[str]:
        """Tear down any `viewdock_*` mode still enabled from a prior run.

        PID-suffixed mode names (see `_build_modeline`) already stop a stale
        mode from colliding with a new one at `--newmode` time, so this isn't
        needed to avoid `BadName`/`RRCreateMode` — `main.py` now also handles
        SIGTERM, so a `kill` (not `kill -9`) tears down cleanly on its own.
        This instead cleans up the *leftover* mode/output enablement from an
        older crash or a `kill -9`, which the PID suffix alone doesn't touch.
        Safe to call unconditionally before `create_virtual_display()` — a
        clean prior exit leaves nothing to find.
        """
        result = subprocess.run(["xrandr", "--query"], check=True, capture_output=True, text=True)
        current_output: str | None = None
        cleaned: list[str] = []
        for line in result.stdout.splitlines():
            status_match = _OUTPUT_STATUS_RE.match(line)
            if status_match:
                current_output = status_match.group(1)
                continue
            mode_match = _STALE_MODE_RE.match(line)
            if mode_match and current_output is not None:
                mode_name = mode_match.group(1)
                subprocess.run(["xrandr", "--output", current_output, "--off"], check=False)
                subprocess.run(["xrandr", "--delmode", current_output, mode_name], check=False)
                subprocess.run(["xrandr", "--rmmode", mode_name], check=False)
                cleaned.append(mode_name)
        if cleaned:
            logger.info("Cleaned up stale virtual output mode(s): %s", cleaned)
        return cleaned

    @staticmethod
    def _build_modeline(config: DisplayConfig) -> tuple[str, list[str]]:
        # capture_width/capture_height, not width/height: the mode this
        # function builds is the actual XRandR pixel geometry mss captures —
        # equal to the logical point size unless VIEWDOCK_DISPLAY_SCALE
        # opts into a sharper native-pixel capture (see DisplayConfig).
        width, height = config.capture_width, config.capture_height

        # PID-suffixed so a mode left behind by a crashed/force-killed prior
        # run can never collide with this run's `--newmode` and fail with
        # RandR's BadName/RRCreateMode. Leftover modes themselves are swept up
        # by cleanup_stale_virtual_outputs().
        mode_name = f"viewdock_{width}x{height}_{config.refresh_hz}_{os.getpid()}"
        # -r: reduced-blanking CVT. Found live: plain `cvt` for 1180x820@60
        # produces a 79.25MHz-pixel-clock mode that a real Intel iGPU
        # (Tiger Lake Iris Xe) refused to activate as a third simultaneous
        # output ("Configure crtc 2 failed") once a real monitor was also
        # plugged in — even though that same GPU had driven 3-4 real
        # monitors simultaneously before, so it wasn't a simultaneous-output
        # *count* limit, just this mode's bandwidth. -r's lower-overhead
        # blanking intervals bring the same resolution down to 68MHz, which
        # worked. No downside for a captured-not-displayed-on-real-hardware
        # virtual mode — reduced blanking exists for exactly this kind of
        # fixed-timing digital path, not CRTs that need the wider blanking.
        cvt = subprocess.run(
            ["cvt", "-r", str(width), str(height), str(config.refresh_hz)],
            check=True,
            capture_output=True,
            text=True,
        )
        match = re.search(r'Modeline\s+"\S+"\s+(.+)', cvt.stdout)
        if not match:
            raise RuntimeError(f"Could not parse `cvt` output: {cvt.stdout!r}")
        modeline = match.group(1).split()
        return mode_name, X11DisplayServer._exact_width_modeline(modeline, width)

    @staticmethod
    def _exact_width_modeline(modeline: list[str], exact_width: int) -> list[str]:
        """Shrink a `cvt -r` modeline's active width back to the exact pixel
        count requested, undoing `cvt`'s multiple-of-8 rounding (e.g. 1180 ->
        1184) that otherwise leaves the stream ~0.3% off the panel's aspect
        ratio — a hairline letterbox on the iPad's aspect-fit.

        `cvt -r`'s reduced-blanking horizontal timing is a fixed-width blank
        (front porch + sync + back porch) tacked onto the active width,
        independent of the active width itself — confirmed empirically
        (`cvt -r 1176 820 60` and `cvt -r 1184 820 60` both produce a 160px
        total horizontal blank). So shaving `delta` pixels off the rounded
        active width and off every horizontal timing figure after it (sync
        start/end, total) by the same `delta` reproduces exactly what `cvt`
        would have produced had it not rounded — same blanking shape, just
        `delta` pixels narrower. The pixel clock is scaled down by the same
        proportion (`htotal` shrinks, so fewer pixels need to be clocked out
        per line to hold the same line time, i.e. the same refresh rate).
        """
        pclk_str, hdisp_str, hss_str, hse_str, htotal_str, *rest = modeline
        hdisp, hss, hse, htotal = int(hdisp_str), int(hss_str), int(hse_str), int(htotal_str)
        delta = hdisp - exact_width
        if delta == 0:
            return modeline

        pclk = float(pclk_str) * (htotal - delta) / htotal
        return [
            f"{pclk:.2f}",
            str(hdisp - delta),
            str(hss - delta),
            str(hse - delta),
            str(htotal - delta),
            *rest,
        ]

    @staticmethod
    def _find_monitor_geometry(output: str) -> dict[str, int]:
        result = subprocess.run(["xrandr", "--query"], check=True, capture_output=True, text=True)
        # Some real GPU drivers (confirmed: Intel modesetting) accept a
        # forced mode on an output with no EDID/hotplug signal but keep
        # reporting it "disconnected" rather than flipping to "connected"
        # the way xf86-video-dummy does — match either, keying on the
        # presence of geometry instead of the connection word.
        pattern = re.compile(rf"^{re.escape(output)} (?:dis)?connected.*?(\d+)x(\d+)\+(\d+)\+(\d+)")
        for line in result.stdout.splitlines():
            match = pattern.match(line)
            if match:
                width, height, left, top = (int(g) for g in match.groups())
                return {"left": left, "top": top, "width": width, "height": height}
        raise RuntimeError(f"Could not find geometry for output {output} after enabling it.")
