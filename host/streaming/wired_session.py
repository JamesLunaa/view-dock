"""One wired session: H.264 video + control messages over a single tunnel.

Counterpart of `webrtc_session.WebRtcSession` for transports that set
`supports_wired_stream` (see `host/transport/adb.py`): same constructor and
`start`/`wait_closed`/`close` interface so `HostRunner` treats them alike, but
video goes out as binary frames on the transport's connection (layout in
`protocol/PROTOCOL.md`, "Wired stream") instead of over WebRTC.
"""

import asyncio
import json
import logging
import struct
import time

import jsonschema
from av import VideoFrame
from websockets.exceptions import ConnectionClosed

from host.config import DisplayConfig
from host.displayserver.base import DisplayServer
from host.input.injector import InputInjector
from host.streaming.wired_encoder import WIRED_FPS, AnnexBEncoder
from host.transport.base import Transport
from protocol import messages, validation

logger = logging.getLogger(__name__)

_FRAME_PTIME = 1.0 / WIRED_FPS
_LOG_EVERY_S = 5.0

_VIDEO_HEADER = struct.Struct(">BBQ")


def _put_latest(queue: asyncio.Queue, item) -> None:
    """Enqueue, dropping the stale item if the next stage hasn't taken it yet —
    a late frame is worth less than the current one, and keeping at most one
    waiting per stage bounds the latency the pipeline can add."""
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    queue.put_nowait(item)


def _to_yuv(array, bgra: bool) -> VideoFrame:
    """Colour-convert a captured frame to the encoder's yuv420p.

    The BGRA path wraps the capture buffer without copying (`from_numpy_buffer`)
    and converts from there, which is both cheaper than RGB24 -> yuv420p and
    skips two copies. The RGB path keeps `from_ndarray`, which copies and so also
    copes with the non-contiguous arrays the channel reorder produces.
    """
    if bgra:
        return VideoFrame.from_numpy_buffer(array, format="bgra").reformat(format="yuv420p")
    return VideoFrame.from_ndarray(array, format="rgb24").reformat(format="yuv420p")


class _StageTimes:
    """Per-stage averages for the periodic log line, to show which one limits fps."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.samples: dict[str, list[float]] = {"capture": [], "convert": [], "encode": []}

    def add(self, stage: str, started: float) -> None:
        self.samples[stage].append((time.perf_counter() - started) * 1000)

    def summary(self) -> str:
        return " ".join(
            f"{stage}={sum(values) / len(values):.1f}ms" for stage, values in self.samples.items() if values
        )


def pack_video_frame(data: bytes, keyframe: bool, pts_us: int) -> bytes:
    flags = messages.WIRED_FLAG_KEYFRAME if keyframe else 0
    return _VIDEO_HEADER.pack(messages.WIRED_FRAME_VIDEO, flags, pts_us) + data


class WiredSession:
    def __init__(
        self,
        display_server: DisplayServer,
        input_injector: InputInjector,
        display_config: DisplayConfig,
    ) -> None:
        self._display_server = display_server
        self._input_injector = input_injector
        self._display_config = display_config
        self._transport: Transport | None = None
        self._closed = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._force_keyframe = True  # the stream always opens on a keyframe
        self._seen_input = False

    async def start(self, transport: Transport) -> None:
        self._transport = transport
        await self._send_control(
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
        await self._send_control(
            {
                "type": messages.TYPE_DISPLAY_INFO,
                "width": self._display_config.capture_width,
                "height": self._display_config.capture_height,
                "refresh_hz": self._display_config.refresh_hz,
                "orientation": orientation,
            }
        )
        self._tasks = [
            asyncio.ensure_future(self._guarded(self._stream_video())),
            asyncio.ensure_future(self._guarded(self._receive_control())),
        ]

    async def wait_closed(self) -> None:
        await self._closed.wait()

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        self._closed.set()

    async def _guarded(self, coroutine) -> None:
        """Ends the session when either loop stops (connection closed, or a bug)."""
        try:
            await coroutine
        except asyncio.CancelledError:
            raise
        except ConnectionClosed as error:
            logger.info("Wired connection closed: %s", error)
        except Exception:
            logger.exception("Wired session loop failed")
        asyncio.ensure_future(self.close())

    async def _send_control(self, message: dict) -> None:
        # A failure here means this side's own message construction drifted
        # from protocol/schema/ — a bug on the host, not the client's.
        validation.validate_message(message)
        assert self._transport is not None
        await self._transport.send_message(json.dumps(message))

    async def _stream_video(self) -> None:
        """Capture -> colour-convert -> encode+send, as three overlapping stages.

        Done one after another a frame costs capture + convert + encode (about
        24 ms at 1440x648), which caps out near 40 fps. As a pipeline each stage
        works on a different frame at the same time, so throughput is set by the
        slowest stage alone (the colour conversion, ~11 ms). The numpy/PyAV/x264
        calls release the GIL, so the stages really run in parallel threads.
        """
        assert self._transport is not None
        loop = asyncio.get_running_loop()
        encoder = AnnexBEncoder(self._display_config.capture_width, self._display_config.capture_height)
        bgra = self._display_server.supports_bgra_capture
        capture = self._display_server.capture_frame_bgra if bgra else self._display_server.capture_frame
        raw_frames: asyncio.Queue = asyncio.Queue(maxsize=1)
        ready_frames: asyncio.Queue = asyncio.Queue(maxsize=1)
        times = _StageTimes()
        started = time.monotonic()

        async def capture_stage() -> None:
            next_deadline = time.monotonic()
            while True:
                now = time.monotonic()
                if next_deadline - now < -_FRAME_PTIME:
                    # Fell behind (a slow capture, or the client not draining the
                    # tunnel fast enough): re-sync rather than burst to catch up,
                    # which would only add latency.
                    next_deadline = now
                else:
                    await asyncio.sleep(max(next_deadline - now, 0))
                next_deadline += _FRAME_PTIME
                began = time.perf_counter()
                captured = await loop.run_in_executor(None, capture)
                times.add("capture", began)
                _put_latest(raw_frames, captured)

        async def convert_stage() -> None:
            while True:
                captured = await raw_frames.get()
                began = time.perf_counter()
                frame = await loop.run_in_executor(None, _to_yuv, captured, bgra)
                times.add("convert", began)
                _put_latest(ready_frames, frame)

        async def encode_stage() -> None:
            assert self._transport is not None
            sent_bytes = frames = 0
            last_log = time.monotonic()
            while True:
                frame = await ready_frames.get()
                force = self._force_keyframe
                self._force_keyframe = False
                pts_us = int((time.monotonic() - started) * 1_000_000)

                began = time.perf_counter()
                packets = await loop.run_in_executor(None, encoder.encode, frame, force)
                times.add("encode", began)
                for data, keyframe in packets:
                    await self._transport.send_message(pack_video_frame(data, keyframe, pts_us))
                    sent_bytes += len(data)
                frames += 1

                if time.monotonic() - last_log >= _LOG_EVERY_S:
                    elapsed = time.monotonic() - last_log
                    logger.info(
                        "wired: fps=%.1f bitrate=%.1fMbps %s",
                        frames / elapsed, sent_bytes * 8 / elapsed / 1e6, times.summary(),
                    )
                    last_log = time.monotonic()
                    sent_bytes = frames = 0
                    times.reset()

        await asyncio.gather(capture_stage(), convert_stage(), encode_stage())

    async def _receive_control(self) -> None:
        assert self._transport is not None
        while True:
            raw = await self._transport.receive_message()
            if isinstance(raw, bytes):
                continue  # clients send no binary frames (yet)
            self._handle_control_message(raw)

    def _handle_control_message(self, raw: str) -> None:
        try:
            message = json.loads(raw)
            validation.validate_message(message)
        except (ValueError, validation.UnknownMessageType, jsonschema.ValidationError) as error:
            logger.warning("Dropping control message that failed schema validation: %s", error)
            return

        message_type = message["type"]
        if message_type == messages.TYPE_INPUT_EVENT:
            if not self._seen_input:
                self._seen_input = True
                logger.info("First input event received (%s)", message["kind"])
            self._input_injector.handle_input_event(message)
        elif message_type == messages.TYPE_KEYFRAME_REQUEST:
            self._force_keyframe = True
        elif message_type == messages.TYPE_BYE:
            asyncio.ensure_future(self.close())
