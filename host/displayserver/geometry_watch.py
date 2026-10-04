# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Notices when the X screen layout changes underneath a running capture.

The captured region is a rectangle in root coordinates, resolved once when
the virtual display is created. But those coordinates are not stable: moving
a monitor in the desktop's display settings re-lays-out every output on the
shared canvas, so the virtual display's origin can move while streaming.
Without noticing, capture keeps grabbing the old rectangle — which by then
usually overlaps a *different* monitor, so the iPad shows a slice of the
real desktop.

RandR reports layout changes as RRScreenChangeNotify events. Subscribing and
draining them non-blockingly is far cheaper than re-running `xrandr --query`
on a timer, and re-resolves the region only when it can actually have moved.
"""

import logging

from Xlib import display as xdisplay
from Xlib.ext import randr

logger = logging.getLogger(__name__)


class ScreenLayoutWatcher:
    def __init__(self) -> None:
        self._display = xdisplay.Display()
        root = self._display.screen().root
        root.xrandr_select_input(randr.RRScreenChangeNotifyMask)
        # Events only start queuing after the request reaches the server.
        self._display.flush()

    def close(self) -> None:
        self._display.close()

    def layout_changed(self) -> bool:
        """True if the screen layout changed since the last call.

        Non-blocking: drains whatever RandR has queued and reports whether
        anything arrived. Safe to call every frame.
        """
        changed = False
        for _ in range(self._display.pending_events()):
            self._display.next_event()
            changed = True
        return changed
