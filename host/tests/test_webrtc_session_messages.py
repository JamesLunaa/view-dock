"""Confirms the messages host/streaming/webrtc_session.py actually constructs
at runtime (hello, display_info) conform to protocol/schema/ — as opposed to
test_protocol_validation.py's hand-written samples, this exercises the real
code path via _send_control_message's own validation call.
"""

import numpy as np
import pytest

from host.config import DisplayConfig
from host.displayserver.base import DisplayServer
from host.streaming.webrtc_session import WebRtcSession


class FakeDisplayServer(DisplayServer):
    def create_virtual_display(self, config):
        pass

    def capture_frame(self):
        return np.zeros((1, 1, 3), dtype=np.uint8)

    def destroy_virtual_display(self):
        pass


class FakeInputInjector:
    def handle_input_event(self, event):
        pass


class RecordingChannel:
    def __init__(self):
        self.sent = []

    def send(self, raw):
        self.sent.append(raw)


@pytest.mark.parametrize(
    "width,height,expected_orientation",
    [(1920, 1080, "landscape"), (1080, 1920, "portrait"), (100, 100, "landscape")],
)
def test_on_control_open_sends_valid_hello_and_display_info(width, height, expected_orientation):
    config = DisplayConfig(width=width, height=height, refresh_hz=60)
    session = WebRtcSession(FakeDisplayServer(), FakeInputInjector(), config)
    session._control_channel = RecordingChannel()

    session._on_control_open()

    assert len(session._control_channel.sent) == 2
    import json

    hello, display_info = (json.loads(raw) for raw in session._control_channel.sent)
    assert hello["type"] == "hello"
    assert display_info["type"] == "display_info"
    assert display_info["orientation"] == expected_orientation
