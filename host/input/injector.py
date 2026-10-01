"""Injects `input_event` messages from the iPad into the Linux input stack
via `uinput`, translating normalized [0,1] coordinates to real pixels on the
virtual display.
"""

import uinput

from host.config import DisplayConfig
from protocol import messages

_DOWN_KINDS = {messages.INPUT_KIND_TOUCH_DOWN, messages.INPUT_KIND_PENCIL_DOWN}
_UP_KINDS = {messages.INPUT_KIND_TOUCH_UP, messages.INPUT_KIND_PENCIL_UP}


class InputInjector:
    def __init__(self, display: DisplayConfig) -> None:
        self._display = display
        # capture_width/capture_height, not width/height: uinput's absolute
        # range must match the real X11 screen pixel coordinates the shared
        # pointer moves in, which is the actual XRandR mode geometry
        # (host/displayserver/x11.py builds the mode at this same size) —
        # equal to width/height unless VIEWDOCK_DISPLAY_SCALE is set.
        self._device = uinput.Device(
            [
                uinput.BTN_TOUCH,
                uinput.ABS_X + (0, display.capture_width, 0, 0),
                uinput.ABS_Y + (0, display.capture_height, 0, 0),
            ],
            name="view-dock-ipad",
        )

    def handle_input_event(self, event: dict) -> None:
        x = round(event["x"] * self._display.capture_width)
        y = round(event["y"] * self._display.capture_height)
        kind = event["kind"]

        if kind in _DOWN_KINDS:
            self._device.emit(uinput.BTN_TOUCH, 1, syn=False)
        elif kind in _UP_KINDS:
            self._device.emit(uinput.BTN_TOUCH, 0, syn=False)

        self._device.emit(uinput.ABS_X, x, syn=False)
        self._device.emit(uinput.ABS_Y, y, syn=True)

    def close(self) -> None:
        self._device.destroy()
