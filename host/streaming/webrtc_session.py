"""WebRTC session: video track sourced from a DisplayServer capture, plus
the `control` data channel carrying protocol/ messages. Reused unchanged
regardless of whether the underlying connection came from `transport/wifi.py`
or `transport/usb.py` — only signaling/connection setup differs per transport.
"""

import asyncio
import json
import logging
import os

import aioice.ice
import jsonschema
from aiortc import RTCDataChannel, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame

from host.config import DisplayConfig
from host.displayserver.base import DisplayServer
from host.input.injector import InputInjector
from host.transport.base import Transport
from protocol import messages, validation

logger = logging.getLogger(__name__)

# aioice's own defaults (5s between ICE consent-freshness checks, 6
# consecutive failures before giving up — RFC 7675) add up to ~30s before an
# unplugged cable or killed app surfaces as connectionState "failed" and
# HostRunner notices the drop. Fine for a protocol implementation, far too
# slow for a UI that's supposed to flip back to "waiting for iPad" promptly.
#
# There's no public per-connection API for this in aiortc/aioice — these are
# plain module globals that aioice.ice.Connection.query_consent() reads by
# name at call time, so patching them here (before any RTCPeerConnection
# exists) takes effect for every connection this process creates. Fragile in
# the sense that it depends on aioice's internals rather than a stable API,
# but there's no other way to tune this short of vendoring the check —
# revisit if an aioice upgrade ever renames/removes these.
#
# Actual wall-clock delay is noticeably more than CONSENT_INTERVAL x
# CONSENT_FAILURES alone: each check also waits up to RETRY_RTO (aioice's
# own default: 0.5s) per *nominated candidate pair* for a STUN response
# before counting as a miss, so it's closer to (CONSENT_INTERVAL +
# ~0.5-1s) x CONSENT_FAILURES — confirmed live (1.5s x 3 measured at
# 6-10s, not the ~4.5s the naive multiplication suggests).
aioice.ice.CONSENT_INTERVAL = float(os.environ.get("VIEWDOCK_ICE_CONSENT_INTERVAL", "1.0"))
aioice.ice.CONSENT_FAILURES = int(os.environ.get("VIEWDOCK_ICE_CONSENT_FAILURES", "2"))
print(
    f"[webrtc_session] ICE consent-freshness tuning: "
    f"interval={aioice.ice.CONSENT_INTERVAL}s, failures={aioice.ice.CONSENT_FAILURES}",
    flush=True,
)


class CaptureVideoTrack(VideoStreamTrack):
    """Wraps DisplayServer.capture_frame() as an aiortc video track."""

    def __init__(self, display_server: DisplayServer) -> None:
        super().__init__()
        self._display_server = display_server

    async def recv(self) -> VideoFrame:
        pts, time_base = await self.next_timestamp()

        loop = asyncio.get_event_loop()
        rgb = await loop.run_in_executor(None, self._display_server.capture_frame)

        frame = VideoFrame.from_ndarray(rgb, format="rgb24")
        frame.pts = pts
        frame.time_base = time_base
        return frame


class WebRtcSession:
    """Owns one peer connection: video track + control data channel."""

    def __init__(
        self,
        display_server: DisplayServer,
        input_injector: InputInjector,
        display_config: DisplayConfig,
    ) -> None:
        self._display_server = display_server
        self._input_injector = input_injector
        self._display_config = display_config
        self._pc = RTCPeerConnection()
        self._control_channel: RTCDataChannel | None = None
        self._closed = asyncio.Event()

    async def start(self, transport: Transport) -> None:
        self._pc.addTrack(CaptureVideoTrack(self._display_server))

        self._control_channel = self._pc.createDataChannel("control")
        self._control_channel.on("open", self._on_control_open)
        self._control_channel.on("message", self._on_control_message)
        self._pc.on("connectionstatechange", self._on_connection_state_change)

        await self._negotiate(transport)

    async def wait_closed(self) -> None:
        await self._closed.wait()

    async def close(self) -> None:
        if self._closed.is_set():
            return
        await self._pc.close()
        self._closed.set()

    async def _negotiate(self, transport: Transport) -> None:
        offer = await self._pc.createOffer()
        await self._pc.setLocalDescription(offer)
        await self._wait_ice_gathering_complete()

        local = self._pc.localDescription
        await transport.send_signal({"sdp": local.sdp, "type": local.type})

        answer = await transport.receive_signal()
        await self._pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
        )

    async def _wait_ice_gathering_complete(self) -> None:
        if self._pc.iceGatheringState == "complete":
            return
        done = asyncio.Event()

        @self._pc.on("icegatheringstatechange")
        def _on_change() -> None:
            if self._pc.iceGatheringState == "complete":
                done.set()

        await done.wait()

    def _on_connection_state_change(self) -> None:
        # Catches an unplugged cable, a killed app, or any other disconnect
        # that never sends a `bye` — aiortc has no "disconnected" state (see
        # its own comment to that effect), only a `failed` ICE/DTLS state
        # reached after connectivity checks stop getting responses, so this
        # fires somewhat later than an unplug than a graceful `bye` would.
        if self._pc.connectionState in ("failed", "closed"):
            asyncio.ensure_future(self.close())

    def _on_control_open(self) -> None:
        self._send_control_message(
            {
                "type": messages.TYPE_HELLO,
                "role": messages.ROLE_HOST,
                "protocol_version": messages.PROTOCOL_VERSION,
            }
        )
        orientation = (
            messages.ORIENTATION_LANDSCAPE
            if self._display_config.width >= self._display_config.height
            else messages.ORIENTATION_PORTRAIT
        )
        self._send_control_message(
            {
                "type": messages.TYPE_DISPLAY_INFO,
                # capture_width/capture_height: the actual video pixel size
                # (equal to width/height unless VIEWDOCK_DISPLAY_SCALE is
                # set) — orientation is unaffected since scaling is uniform.
                "width": self._display_config.capture_width,
                "height": self._display_config.capture_height,
                "refresh_hz": self._display_config.refresh_hz,
                "orientation": orientation,
            }
        )

    def _send_control_message(self, message: dict) -> None:
        assert self._control_channel is not None
        # A validation failure here means host's own message construction
        # drifted from protocol/schema/ — a bug on this side, not the iPad's.
        validation.validate_message(message)
        self._control_channel.send(json.dumps(message))

    def _on_control_message(self, raw: str) -> None:
        message = json.loads(raw)

        try:
            validation.validate_message(message)
        except (validation.UnknownMessageType, jsonschema.ValidationError) as error:
            logger.warning("Dropping control message that failed schema validation: %s", error)
            return

        message_type = message["type"]
        if message_type == messages.TYPE_INPUT_EVENT:
            self._input_injector.handle_input_event(message)
        elif message_type == messages.TYPE_STATS:
            pass  # TODO: feed into adaptive bitrate logic.
        elif message_type == messages.TYPE_BYE:
            asyncio.ensure_future(self.close())
