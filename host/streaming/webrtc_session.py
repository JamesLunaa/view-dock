"""WebRTC session: video track sourced from a DisplayServer capture, plus
the `control` data channel carrying protocol/ messages. Reused unchanged
regardless of whether the underlying connection came from `transport/wifi.py`
or `transport/usb.py` — only signaling/connection setup differs per transport.
"""

import json

from aiortc import RTCPeerConnection, RTCDataChannel, VideoStreamTrack
from av import VideoFrame

from host.displayserver.base import DisplayServer
from protocol import messages


class CaptureVideoTrack(VideoStreamTrack):
    """Wraps DisplayServer.capture_frame() as an aiortc video track."""

    def __init__(self, display_server: DisplayServer) -> None:
        super().__init__()
        self._display_server = display_server

    async def recv(self) -> VideoFrame:
        # TODO: pace to the configured refresh rate, convert the captured
        # RGB array to a VideoFrame, and stamp pts/time_base.
        raise NotImplementedError


class WebRtcSession:
    """Owns one peer connection: video track + control data channel."""

    def __init__(self, display_server: DisplayServer) -> None:
        self._display_server = display_server
        self._pc = RTCPeerConnection()
        self._control_channel: RTCDataChannel | None = None

    async def start(self) -> None:
        self._pc.addTrack(CaptureVideoTrack(self._display_server))
        self._control_channel = self._pc.createDataChannel("control")
        self._control_channel.on("message", self._on_control_message)
        # TODO: send `hello` once the channel opens, then `display_info`.

    def _on_control_message(self, raw: str) -> None:
        message = json.loads(raw)
        # TODO: dispatch on message["type"] (see protocol/PROTOCOL.md):
        #   messages.TYPE_INPUT_EVENT -> host/input/injector.py
        #   messages.TYPE_STATS       -> adaptive bitrate logic
        #   messages.TYPE_BYE         -> tear down the session
        raise NotImplementedError

    async def close(self) -> None:
        await self._pc.close()
