"""X11 implementation of DisplayServer.

Virtual output is created via `xrandr` (dummy output / `--addmode`); frames
are captured via `mss`. This is the phase 1 implementation referenced in
CLAUDE.md.

Requires a disconnected output already present in the X server — in practice
this means the `xorg-dummy` (aka `xf86-video-dummy`) driver configured for at
least one extra head, since real GPU drivers don't expose a spare connector
to attach a synthetic mode to. See host/README.md.
"""

import re
import subprocess

import numpy as np
import mss

from host.config import DisplayConfig
from host.displayserver.base import DisplayServer

_DISCONNECTED_RE = re.compile(r"^(\S+) disconnected")


class X11DisplayServer(DisplayServer):
    def __init__(self) -> None:
        self._output_name: str | None = None
        self._mode_name: str | None = None
        self._sct: mss.base.MSSBase | None = None
        self._monitor: dict[str, int] | None = None

    def create_virtual_display(self, config: DisplayConfig) -> None:
        output = self._find_disconnected_output()
        if output is None:
            raise RuntimeError(
                "No disconnected output available for the virtual display. "
                "Configure a dummy output (xf86-video-dummy) — see host/README.md."
            )

        mode_name, modeline = self._build_modeline(config)
        subprocess.run(["xrandr", "--newmode", mode_name, *modeline], check=True)
        subprocess.run(["xrandr", "--addmode", output, mode_name], check=True)
        subprocess.run(["xrandr", "--output", output, "--mode", mode_name], check=True)

        self._output_name = output
        self._mode_name = mode_name
        self._sct = mss.mss()
        self._monitor = self._find_monitor_geometry(output)

    def capture_frame(self) -> np.ndarray:
        if self._sct is None or self._monitor is None:
            raise RuntimeError("Virtual display not created; call create_virtual_display() first.")
        shot = self._sct.grab(self._monitor)
        # mss returns BGRA; drop alpha and reorder to RGB for the encoder.
        return np.asarray(shot)[:, :, [2, 1, 0]]

    def destroy_virtual_display(self) -> None:
        if self._output_name is None:
            return

        subprocess.run(["xrandr", "--output", self._output_name, "--off"], check=False)
        if self._mode_name is not None:
            subprocess.run(["xrandr", "--delmode", self._output_name, self._mode_name], check=False)
            subprocess.run(["xrandr", "--rmmode", self._mode_name], check=False)
        if self._sct is not None:
            self._sct.close()

        self._output_name = None
        self._mode_name = None
        self._sct = None
        self._monitor = None

    @staticmethod
    def _find_disconnected_output() -> str | None:
        result = subprocess.run(["xrandr", "--query"], check=True, capture_output=True, text=True)
        for line in result.stdout.splitlines():
            match = _DISCONNECTED_RE.match(line)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _build_modeline(config: DisplayConfig) -> tuple[str, list[str]]:
        mode_name = f"viewdock_{config.width}x{config.height}_{config.refresh_hz}"
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
        pattern = re.compile(rf"^{re.escape(output)} connected.*?(\d+)x(\d+)\+(\d+)\+(\d+)")
        for line in result.stdout.splitlines():
            match = pattern.match(line)
            if match:
                width, height, left, top = (int(g) for g in match.groups())
                return {"left": left, "top": top, "width": width, "height": height}
        raise RuntimeError(f"Could not find geometry for output {output} after enabling it.")
