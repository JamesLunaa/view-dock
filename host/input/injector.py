"""Injects `input_event` messages from the iPad into the Linux input stack
via `uinput`, translating normalized [0,1] coordinates to real pixels on the
virtual display.
"""

from host.config import DisplayConfig


class InputInjector:
    def __init__(self, display: DisplayConfig) -> None:
        self._display = display

    def handle_input_event(self, event: dict) -> None:
        # TODO: map event["kind"] (see protocol/PROTOCOL.md) to uinput
        # touch/pen events, scaling event["x"]/event["y"] by
        # self._display.width/height.
        raise NotImplementedError
