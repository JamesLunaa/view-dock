"""Covers the wired (USB) stream: the encoder emits a self-contained Annex-B
stream a phone decoder can start from, and `WiredSession` puts the right
messages on the tunnel — hello/display_info first, a keyframe first, keyframes
on request — and routes input back to the injector.
"""

import asyncio
import json
import struct

import numpy as np
import pytest
from av import VideoFrame
from websockets.exceptions import ConnectionClosedOK
from websockets.frames import Close

from host.config import DisplayConfig
from host.streaming.wired_encoder import AnnexBEncoder
from host.streaming.wired_session import WiredSession, pack_video_frame
from host.transport.base import Transport
from protocol import messages

WIDTH, HEIGHT = 320, 144  # tiny, so x264 is instant


def _nal_types(annexb: bytes) -> list[int]:
    types, i = [], 0
    while True:
        i = annexb.find(b"\x00\x00\x01", i)
        if i < 0:
            return types
        types.append(annexb[i + 3] & 0x1F)
        i += 3


def _frame(value: int = 0) -> VideoFrame:
    return VideoFrame.from_ndarray(np.full((HEIGHT, WIDTH, 3), value, dtype=np.uint8), format="rgb24")


def test_first_packet_is_a_self_contained_keyframe():
    encoder = AnnexBEncoder(WIDTH, HEIGHT, fps=30)
    packets = encoder.encode(_frame(10), force_keyframe=True)

    data, keyframe = packets[0]
    assert keyframe
    assert data.startswith((b"\x00\x00\x00\x01", b"\x00\x00\x01")), "must be Annex-B"
    # In-band parameter sets are what lets MediaCodec start without extradata.
    assert {7, 8, 5} <= set(_nal_types(data)), "keyframe needs SPS, PPS and an IDR slice"


def test_later_frames_are_not_keyframes_unless_forced():
    encoder = AnnexBEncoder(WIDTH, HEIGHT, fps=30)
    encoder.encode(_frame(10), force_keyframe=True)
    flags = [kf for _ in range(3) for _, kf in encoder.encode(_frame(11))]
    assert flags and not any(flags)

    forced = encoder.encode(_frame(12), force_keyframe=True)
    assert forced and forced[0][1]


def test_video_frame_header_layout():
    packed = pack_video_frame(b"\xAA\xBB", keyframe=True, pts_us=0x0102030405060708)
    assert packed[0] == messages.WIRED_FRAME_VIDEO
    assert packed[1] & messages.WIRED_FLAG_KEYFRAME
    assert struct.unpack(">Q", packed[2:10])[0] == 0x0102030405060708
    assert packed[messages.WIRED_VIDEO_HEADER_SIZE:] == b"\xAA\xBB"
    assert pack_video_frame(b"", keyframe=False, pts_us=0)[1] == 0


class FakeWiredTransport(Transport):
    supports_wired_stream = True

    def __init__(self) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: asyncio.Queue = asyncio.Queue()

    async def is_available(self) -> bool:
        return True

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def send_signal(self, message: dict) -> None: ...
    async def receive_signal(self) -> dict: ...

    async def send_message(self, data) -> None:
        self.sent.append(data)

    async def receive_message(self):
        item = await self.incoming.get()
        if isinstance(item, Exception):
            raise item
        return item


class FakeDisplay:
    def capture_frame(self):
        return np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)


class RecordingInjector:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def handle_input_event(self, event: dict) -> None:
        self.events.append(event)


def _session(transport):
    injector = RecordingInjector()
    config = DisplayConfig(width=WIDTH, height=HEIGHT)
    return WiredSession(FakeDisplay(), injector, config), injector


async def _wait_for(predicate, timeout=3.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.01)


def _video(transport):
    return [m for m in transport.sent if isinstance(m, bytes)]


def test_session_opens_with_hello_display_info_then_a_keyframe():
    async def body():
        transport = FakeWiredTransport()
        session, _ = _session(transport)
        await session.start(transport)
        await _wait_for(lambda: len(_video(transport)) >= 3)
        await session.close()

        texts = [json.loads(m) for m in transport.sent if isinstance(m, str)]
        assert [t["type"] for t in texts[:2]] == ["hello", "display_info"]
        assert texts[0]["role"] == "host"
        assert (texts[1]["width"], texts[1]["height"]) == (WIDTH, HEIGHT)
        # hello/display_info precede any video on the wire
        assert isinstance(transport.sent[0], str) and isinstance(transport.sent[1], str)

        first = _video(transport)[0]
        assert first[1] & messages.WIRED_FLAG_KEYFRAME, "the stream must open on a keyframe"
        assert not _video(transport)[1][1] & messages.WIRED_FLAG_KEYFRAME

    asyncio.run(body())


def test_keyframe_request_forces_the_next_frame_to_be_a_keyframe():
    async def body():
        transport = FakeWiredTransport()
        session, _ = _session(transport)
        await session.start(transport)
        await _wait_for(lambda: len(_video(transport)) >= 3)

        seen = len(_video(transport))
        await transport.incoming.put(json.dumps({"type": messages.TYPE_KEYFRAME_REQUEST}))
        await _wait_for(lambda: any(v[1] & 1 for v in _video(transport)[seen:]))
        await session.close()

    asyncio.run(body())


def test_input_events_reach_the_injector_and_bad_ones_are_dropped():
    async def body():
        transport = FakeWiredTransport()
        session, injector = _session(transport)
        await session.start(transport)

        good = {
            "type": messages.TYPE_INPUT_EVENT,
            "kind": messages.INPUT_KIND_TOUCH_DOWN,
            "x": 0.5,
            "y": 0.25,
            "pressure": 0.0,
            "timestamp_ms": 1,
        }
        await transport.incoming.put(json.dumps({**good, "x": 7.0}))  # out of schema range
        await transport.incoming.put("not json")
        await transport.incoming.put(json.dumps(good))
        await _wait_for(lambda: injector.events)
        await session.close()

        assert injector.events == [good]

    asyncio.run(body())


@pytest.mark.parametrize("how", ["connection_closed", "bye"])
def test_session_ends_when_the_tunnel_closes_or_the_client_says_bye(how):
    async def body():
        transport = FakeWiredTransport()
        session, _ = _session(transport)
        await session.start(transport)

        if how == "bye":
            await transport.incoming.put(json.dumps({"type": "bye", "reason": "user_disconnected"}))
        else:
            await transport.incoming.put(ConnectionClosedOK(Close(1001, ""), Close(1001, ""), rcvd_then_sent=True))
        await asyncio.wait_for(session.wait_closed(), timeout=2)

    asyncio.run(body())


def test_stream_decodes_with_an_independent_h264_decoder():
    """The phone's MediaCodec isn't available in CI, so check the bitstream with
    libavcodec's decoder instead: fed only what goes on the wire (Annex-B
    access units, parameter sets in-band on the keyframe), it must yield every
    frame at the right size — i.e. decoding can start from the stream alone."""
    import av

    encoder = AnnexBEncoder(WIDTH, HEIGHT, fps=30)
    access_units = []
    for i in range(12):
        for data, _ in encoder.encode(_frame(i * 10), force_keyframe=(i == 0)):
            access_units.append(data)
    assert len(access_units) == 12, "zerolatency must emit one access unit per frame, with no encoder delay"

    decoder = av.CodecContext.create("h264", "r")
    frames = []
    # One access unit per packet, exactly how MediaCodec is fed on the phone.
    for data in access_units:
        frames.extend(decoder.decode(av.Packet(data)))
    frames.extend(decoder.decode(None))  # flush

    assert len(frames) == 12
    assert {(f.width, f.height) for f in frames} == {(WIDTH, HEIGHT)}
