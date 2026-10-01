"""Confirms the messages host/streaming/webrtc_session.py actually constructs
at runtime (hello, display_info) conform to protocol/schema/ — as opposed to
test_protocol_validation.py's hand-written samples, this exercises the real
code path via _send_control_message's own validation call.
"""

import asyncio

import aioice.ice
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


def test_display_info_reports_capture_pixels_not_logical_points_under_scale():
    """VIEWDOCK_DISPLAY_SCALE (DisplayConfig.capture_scale) makes the actual
    video pixel size a multiple of the logical point size — display_info
    should describe the former (the real stream), not the latter."""
    config = DisplayConfig(width=1180, height=820, refresh_hz=60, capture_scale=2)
    session = WebRtcSession(FakeDisplayServer(), FakeInputInjector(), config)
    session._control_channel = RecordingChannel()

    session._on_control_open()

    import json

    _hello, display_info = (json.loads(raw) for raw in session._control_channel.sent)
    assert (display_info["width"], display_info["height"]) == (2360, 1640)


def test_ice_consent_timing_is_patched_to_something_faster_than_aioice_default():
    """aioice's own defaults (CONSENT_INTERVAL=5, CONSENT_FAILURES=6) add up
    to ~30s before an unplugged cable surfaces as connectionState "failed" —
    importing webrtc_session.py patches these module globals to something
    faster (see its own comment for why there's no cleaner API for this).
    If an aioice upgrade ever renames/removes these, this fails loudly
    instead of silently reverting to the slow default."""
    assert aioice.ice.CONSENT_INTERVAL * aioice.ice.CONSENT_FAILURES < 15


class FakePeerConnection:
    """Stands in for aiortc's RTCPeerConnection, whose connectionState is a
    read-only property aiortc itself manages — can't be set directly on a
    real instance, so this is a minimal substitute for the one property
    _on_connection_state_change reads."""

    def __init__(self, connection_state: str) -> None:
        self.connectionState = connection_state
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("terminal_state", ["failed", "closed"])
def test_connection_state_change_to_terminal_state_closes_session(terminal_state):
    """Covers the actual feature: an unplugged cable or killed app never
    sends `bye`, so without watching connectionState the host would think
    it's still connected forever. aiortc has no 'disconnected' state —
    only 'failed' once ICE/DTLS connectivity checks stop getting
    responses — so that and 'closed' are what this has to catch."""

    async def body():
        session = WebRtcSession(FakeDisplayServer(), FakeInputInjector(), DisplayConfig())
        session._pc = FakePeerConnection(connection_state=terminal_state)

        session._on_connection_state_change()
        await asyncio.sleep(0)  # let the ensure_future'd close() run

        assert session._pc.closed
        assert session._closed.is_set()

    asyncio.run(body())


def test_connection_state_change_to_connected_does_not_close_session():
    async def body():
        session = WebRtcSession(FakeDisplayServer(), FakeInputInjector(), DisplayConfig())
        session._pc = FakePeerConnection(connection_state="connected")

        session._on_connection_state_change()
        await asyncio.sleep(0)

        assert not session._pc.closed
        assert not session._closed.is_set()

    asyncio.run(body())
