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

import numpy as np
import mss

from host.config import DisplayConfig
from host.displayserver.base import DisplayServer
from host.displayserver.cursor import X11CursorCompositor
from host.displayserver.geometry_watch import ScreenLayoutWatcher

logger = logging.getLogger(__name__)

_OUTPUT_STATUS_RE = re.compile(r"^(\S+) (?:dis)?connected\b(.*)$")
_GEOMETRY_RE = re.compile(r"\d+x\d+\+\d+\+\d+")
_PRIMARY_RE = re.compile(r"^(\S+) connected primary")
_STALE_MODE_RE = re.compile(r"^\s+(viewdock_\S+)")
_DISCONNECTED_RE = re.compile(r"^(\S+) disconnected\b")


class X11DisplayServer(DisplayServer):
    def __init__(self) -> None:
        self._output_name: str | None = None
        self._mode_name: str | None = None
        self._sct: mss.base.MSSBase | None = None
        self._monitor: dict[str, int] | None = None
        self._cursor: X11CursorCompositor | None = None
        self._layout_watcher: ScreenLayoutWatcher | None = None

    def create_virtual_display(self, config: DisplayConfig) -> None:
        output = self.find_available_output()
        if output is None:
            raise RuntimeError(
                "No spare output available for the virtual display. Configure a "
                "dummy output (xf86-video-dummy) or force a real GPU output on at "
                "the kernel/DRM level — see host/README.md."
            )

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
        subprocess.run(enable_command, check=True)

        self._output_name = output
        self._mode_name = mode_name
        self._sct = mss.mss()
        self._monitor = self._find_monitor_geometry(output)

        try:
            self._cursor = X11CursorCompositor()
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

    def capture_frame(self) -> np.ndarray:
        if self._sct is None or self._monitor is None:
            raise RuntimeError("Virtual display not created; call create_virtual_display() first.")

        self._refresh_geometry_if_moved()
        shot = self._sct.grab(self._monitor)
        # mss returns BGRA; drop alpha and reorder to RGB for the encoder.
        # Advanced indexing copies, so the result is safe to draw into below.
        frame = np.asarray(shot)[:, :, [2, 1, 0]]

        if self._cursor is not None:
            try:
                self._cursor.composite(frame, self._monitor)
            except Exception:
                logger.warning("Cursor overlay failed; disabling it.", exc_info=True)
                self._cursor.close()
                self._cursor = None

        return frame

    def _refresh_geometry_if_moved(self) -> None:
        """Re-resolve the capture rectangle after a display rearrangement.

        Only does real work when RandR says the layout changed, so the common
        case costs one non-blocking event-queue check per frame.
        """
        if self._layout_watcher is None or self._output_name is None:
            return
        if not self._layout_watcher.layout_changed():
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
    def find_available_output() -> str | None:
        result = subprocess.run(["xrandr", "--query"], check=True, capture_output=True, text=True)
        for line in result.stdout.splitlines():
            match = _OUTPUT_STATUS_RE.match(line)
            if match and not _GEOMETRY_RE.search(match.group(2)):
                return match.group(1)
        return None

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
        # PID-suffixed so a mode left behind by a crashed/force-killed prior
        # run can never collide with this run's `--newmode` and fail with
        # RandR's BadName/RRCreateMode. Leftover modes themselves are swept up
        # by cleanup_stale_virtual_outputs().
        mode_name = f"viewdock_{config.width}x{config.height}_{config.refresh_hz}_{os.getpid()}"
        cvt = subprocess.run(
            ["cvt", str(config.width), str(config.height), str(config.refresh_hz)],
            check=True,
            capture_output=True,
            text=True,
        )
        match = re.search(r'Modeline\s+"\S+"\s+(.+)', cvt.stdout)
        if not match:
            raise RuntimeError(f"Could not parse `cvt` output: {cvt.stdout!r}")
        return mode_name, match.group(1).split()

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
