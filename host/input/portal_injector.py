# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Injects `input_event` messages through the RemoteDesktop portal instead of
uinput — the GNOME Wayland path, where a uinput touchscreen can't be pinned
to a virtual monitor. Each event becomes an absolute pointer motion addressed
to the virtual monitor's stream (so it lands there wherever the monitor sits
in the layout), with the left button held while a finger or pencil is down.
Same interface as `InputInjector`.
"""

from host.config import DisplayConfig
from host.displayserver.portal import BTN_LEFT, ScreenCastPortal
from protocol import messages

_DOWN_KINDS = {messages.INPUT_KIND_TOUCH_DOWN, messages.INPUT_KIND_PENCIL_DOWN}
_UP_KINDS = {messages.INPUT_KIND_TOUCH_UP, messages.INPUT_KIND_PENCIL_UP}


class PortalPointerInjector:
    def __init__(self, portal: ScreenCastPortal, node_id: int, display: DisplayConfig) -> None:
        self._portal = portal
        self._node_id = node_id
        # The stream's logical coordinate space. Mutter gives a virtual
        # monitor scale 1, so that is its pixel size.
        self._width = display.capture_width
        self._height = display.capture_height

    def handle_input_event(self, event: dict) -> None:
        x = min(max(event["x"], 0.0), 1.0) * (self._width - 1)
        y = min(max(event["y"], 0.0), 1.0) * (self._height - 1)
        kind = event["kind"]

        # Move first, so a press lands where the finger went down.
        self._portal.pointer_motion_absolute(self._node_id, x, y)
        if kind in _DOWN_KINDS:
            self._portal.pointer_button(BTN_LEFT, True)
        elif kind in _UP_KINDS:
            self._portal.pointer_button(BTN_LEFT, False)

    def close(self) -> None:
        # The portal session belongs to the display server, which ends it.
        pass
