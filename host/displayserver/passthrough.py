# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Fallback DisplayServer that captures the host's real primary monitor
instead of creating a virtual one via `xrandr`.

Useful for exercising the rest of the pipeline (WebRTC video/input) on a
machine without a `xf86-video-dummy`-configured Xorg session — e.g. a
Wayland desktop, where Xwayland can't create synthetic outputs the way
`xrandr --newmode`/`--addmode` expects. See host/README.md for the real
virtual-display path (`x11.py`), which this is not a replacement for.
"""

import numpy as np
import mss

from host.config import DisplayConfig
from host.displayserver.base import DisplayServer


class PassthroughDisplayServer(DisplayServer):
    def __init__(self) -> None:
        self._sct: mss.base.MSSBase | None = None
        self._monitor: dict[str, int] | None = None

    def create_virtual_display(self, config: DisplayConfig) -> None:
        self._sct = mss.mss()
        # monitors[0] is the union of every monitor; [1] is the primary one.
        self._monitor = self._sct.monitors[1]
        # No virtual display was actually created — correct the config in
        # place so display_info (sent to the iPad) and input coordinate
        # mapping match what's really being captured.
        config.width = self._monitor["width"]
        config.height = self._monitor["height"]

    def capture_frame(self) -> np.ndarray:
        if self._sct is None or self._monitor is None:
            raise RuntimeError("Display not created; call create_virtual_display() first.")
        shot = self._sct.grab(self._monitor)
        return np.asarray(shot)[:, :, [2, 1, 0]]

    def destroy_virtual_display(self) -> None:
        if self._sct is not None:
            self._sct.close()
        self._sct = None
        self._monitor = None
