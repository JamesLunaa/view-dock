"""WebRTC session: video track sourced from a DisplayServer capture, plus
the `control` data channel carrying protocol/ messages. Reused unchanged
regardless of whether the underlying connection came from `transport/wifi.py`
or `transport/usb.py` — only signaling/connection setup differs per transport.
"""

import asyncio
import fractions
import json
import logging
import os
import time

import aioice.ice
import jsonschema
from aiortc import RTCDataChannel, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.mediastreams import VIDEO_CLOCK_RATE, VIDEO_TIME_BASE, MediaStreamError
from av import VideoFrame

from host.config import DisplayConfig
from host.displayserver.base import DisplayServer
from host.input.injector import InputInjector
from host.streaming import encoder_tuning
from host.streaming.bitrate_controller import BitrateController, NetworkSample
from host.streaming.metrics import PipelineMetrics
from host.transport.base import Transport
from protocol import messages, validation

logger = logging.getLogger(__name__)

_LOOP_LAG_TICK_S = 0.1
_LOOP_LAG_WARN_S = 0.3

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


_FRAME_PTIME = 1.0 / encoder_tuning.FRAME_RATE
_MONITOR_INTERVAL_S = 1.0
_METRICS_LOG_EVERY_S = 5.0
# An iPad `stats` message older than this is ignored when sampling the network.
_IPAD_STATS_MAX_AGE_S = 3.0


class CaptureVideoTrack(VideoStreamTrack):
    """Wraps DisplayServer.capture_frame() as an aiortc video track."""

    def __init__(self, display_server: DisplayServer, metrics: PipelineMetrics | None = None) -> None:
        super().__init__()
        self._display_server = display_server
        self._metrics = metrics or PipelineMetrics()

    async def next_timestamp(self) -> tuple[int, fractions.Fraction]:
        # Same deadline-based pacing as aiortc's VideoStreamTrack, except it
        # re-syncs instead of bursting when it falls behind: aiortc's version
        # keeps advancing a fixed step from the *original* start time, so one
        # slow capture (a heavy window drag) is followed by back-to-back
        # frames racing to catch up — a visible hitch plus a queue that adds
        # latency. Dropping the missed slots keeps the stream current.
        if self.readyState != "live":
            raise MediaStreamError

        if hasattr(self, "_timestamp"):
            self._timestamp += int(_FRAME_PTIME * VIDEO_CLOCK_RATE)
            wait = self._start + (self._timestamp / VIDEO_CLOCK_RATE) - time.time()
            if wait < -_FRAME_PTIME:
                self._start = time.time() - self._timestamp / VIDEO_CLOCK_RATE
            else:
                await asyncio.sleep(max(wait, 0))
        else:
            self._start = time.time()
            self._timestamp = 0
        return self._timestamp, VIDEO_TIME_BASE

    async def recv(self) -> VideoFrame:
        pts, time_base = await self.next_timestamp()

        loop = asyncio.get_event_loop()
        started = time.perf_counter()
        rgb = await loop.run_in_executor(None, self._display_server.capture_frame)
        captured = time.perf_counter()

        frame = VideoFrame.from_ndarray(rgb, format="rgb24")
        frame.pts = pts
        frame.time_base = time_base
        self._metrics.frame_produced(
            captured, (captured - started) * 1000, (time.perf_counter() - captured) * 1000
        )
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
        self._metrics = PipelineMetrics()
        self._bitrate = BitrateController(
            encoder_tuning.MIN_BITRATE,
            encoder_tuning.MAX_BITRATE,
            encoder_tuning.INITIAL_BITRATE,
            target_fps=encoder_tuning.FRAME_RATE,
        )
        self._ipad_stats: tuple[float, NetworkSample] | None = None
        self._monitor_task: asyncio.Task | None = None
        self._loop_lag_task: asyncio.Task | None = None
        self._seen_input = False

    async def start(self, transport: Transport) -> None:
        encoder_tuning.install()
        self._pc.addTrack(CaptureVideoTrack(self._display_server, self._metrics))
        for transceiver in self._pc.getTransceivers():
            if transceiver.kind == "video":
                transceiver.setCodecPreferences(encoder_tuning.preferred_codecs())

        self._control_channel = self._pc.createDataChannel("control")
        self._control_channel.on("open", self._on_control_open)
        self._control_channel.on("message", self._on_control_message)
        self._pc.on("connectionstatechange", self._on_connection_state_change)

        await self._negotiate(transport)
        self._monitor_task = asyncio.ensure_future(self._monitor_stream())
        self._loop_lag_task = asyncio.ensure_future(self._watch_loop_lag())

    async def wait_closed(self) -> None:
        await self._closed.wait()

    async def close(self) -> None:
        if self._closed.is_set():
            return
        if self._monitor_task is not None:
            self._monitor_task.cancel()
        if self._loop_lag_task is not None:
            self._loop_lag_task.cancel()
        await self._pc.close()
        self._closed.set()

    async def _watch_loop_lag(self) -> None:
        """Warns when the event loop was blocked for a noticeable time.

        ICE consent checks and the media itself run on this loop, so a stall of
        a couple of seconds looks to both ends exactly like a dead network
        (`Consent to send expired`). Logging stalls makes "the host froze" and
        "the link dropped" distinguishable from the log alone.
        """
        while True:
            started = time.monotonic()
            await asyncio.sleep(_LOOP_LAG_TICK_S)
            lag = time.monotonic() - started - _LOOP_LAG_TICK_S
            if lag > _LOOP_LAG_WARN_S:
                logger.warning("Event loop stalled for %.0f ms", lag * 1000)

    async def _monitor_stream(self) -> None:
        """Once a second: sample the network, adapt bitrate; every few
        seconds, log the pipeline timings."""
        last_log = time.monotonic()
        while True:
            await asyncio.sleep(_MONITOR_INTERVAL_S)
            try:
                now = time.monotonic()
                sample = await self._sample_network(now)
                self._metrics.rtt_ms = sample.rtt_ms
                self._metrics.loss_fraction = sample.loss_fraction
                self._metrics.encode_ms.extend(encoder_tuning.drain_encode_ms())

                new_bitrate = self._bitrate.update(sample, now)
                if new_bitrate is not None:
                    applied = encoder_tuning.set_target_bitrate(new_bitrate)
                    logger.info(
                        "Adaptive bitrate -> %.2f Mbps (rtt=%s loss=%s fps=%s)",
                        applied / 1e6, sample.rtt_ms, sample.loss_fraction, sample.fps,
                    )
                self._metrics.bitrate_bps = encoder_tuning.current_target_bitrate()

                if now - last_log >= _METRICS_LOG_EVERY_S:
                    last_log = now
                    self._metrics.log()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Stream monitor tick failed", exc_info=True)

    async def _sample_network(self, now: float) -> NetworkSample:
        rtt_ms = loss = None
        for report in (await self._pc.getStats()).values():
            if report.type == "remote-inbound-rtp" and report.kind == "video":
                if report.roundTripTime is not None:
                    rtt_ms = report.roundTripTime * 1000
                # RTCP carries fraction lost as a raw 0-255 byte.
                loss = report.fractionLost / 256
        fps = None
        if self._ipad_stats is not None and now - self._ipad_stats[0] <= _IPAD_STATS_MAX_AGE_S:
            ipad = self._ipad_stats[1]
            fps = ipad.fps
            if rtt_ms is None:
                rtt_ms = ipad.rtt_ms
        return NetworkSample(rtt_ms=rtt_ms, loss_fraction=loss, fps=fps)

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
            if not self._seen_input:
                self._seen_input = True
                logger.info("First input event received (%s)", message["kind"])
            self._input_injector.handle_input_event(message)
        elif message_type == messages.TYPE_STATS:
            self._ipad_stats = (
                time.monotonic(),
                NetworkSample(rtt_ms=message["rtt_ms"], fps=message["fps"]),
            )
        elif message_type == messages.TYPE_BYE:
            asyncio.ensure_future(self.close())
