"""Tuned H.264 encoder for aiortc's video sender.

aiortc's stock `H264Encoder` is built for webcam calls: 1 Mbps start, clamped
to 0.5-3 Mbps, x264's default preset and an ~8s keyframe interval. A desktop
at 1180x820 full of text needs far more headroom than that — the ceiling, not
CPU, was what made the stream look soft (libx264 `veryfast` costs ~4ms/frame
at this size, a small slice of the 33ms frame budget).

aiortc has no public hook for encoder options, so this subclasses
`H264Encoder` and swaps itself in by patching the `get_encoder` name that
`aiortc.rtcrtpsender` imported. Like the aioice patch in `webrtc_session.py`
this leans on aiortc internals — revisit if an aiortc upgrade breaks it
(`tests/test_encoder_tuning.py` covers the seams).
"""

import fractions
import logging
import os
import threading
import time
import weakref

import av
import aiortc.rtcrtpsender
import aiortc.codecs.h264 as aiortc_h264
from aiortc.codecs import get_encoder as _stock_get_encoder

logger = logging.getLogger(__name__)

MIN_BITRATE = int(float(os.environ.get("VIEWDOCK_MIN_BITRATE_MBPS", "1.0")) * 1_000_000)
MAX_BITRATE = int(float(os.environ.get("VIEWDOCK_MAX_BITRATE_MBPS", "10.0")) * 1_000_000)
INITIAL_BITRATE = int(float(os.environ.get("VIEWDOCK_INITIAL_BITRATE_MBPS", "6.0")) * 1_000_000)
# libx264 preset: ultrafast ~2.6ms/frame, veryfast ~4ms, faster ~7-12ms
# (1180x820, one core, measured). veryfast buys noticeably better quality per
# bit than ultrafast for text while staying well inside the frame budget.
PRESET = os.environ.get("VIEWDOCK_X264_PRESET", "veryfast")
FRAME_RATE = int(os.environ.get("VIEWDOCK_TARGET_FPS", "30"))
# Seconds between forced keyframes. Loss is recovered via PLI, so periodic
# keyframes are only a safety net — and each one is a visible blur-then-
# sharpen pulse on static text (an I-frame is the costliest frame to encode
# well), so it must be rare. 2s was tried first and pulsed noticeably.
KEYFRAME_INTERVAL_S = float(os.environ.get("VIEWDOCK_KEYFRAME_INTERVAL", "30.0"))

_live_encoders: "weakref.WeakSet[TunedH264Encoder]" = weakref.WeakSet()
_lock = threading.Lock()


class TunedH264Encoder(aiortc_h264.H264Encoder):
    def __init__(self) -> None:
        super().__init__()
        self.target_bitrate = INITIAL_BITRATE
        self.encode_ms_recent: list[float] = []
        with _lock:
            _live_encoders.add(self)

    @property
    def target_bitrate(self) -> int:
        return self._tuned_target

    @target_bitrate.setter
    def target_bitrate(self, bitrate: int) -> None:
        # Also reached from aiortc's REMB handling, so clamp to *our* range.
        self._tuned_target = max(MIN_BITRATE, min(int(bitrate), MAX_BITRATE))

    def _encode_frame(self, frame: av.VideoFrame, force_keyframe: bool):
        # aiortc rebuilds the codec context when size or target bitrate
        # drifts >10% (which yields a keyframe) — same rule kept here.
        if self.codec and (
            frame.width != self.codec.width
            or frame.height != self.codec.height
            or abs(self.target_bitrate - self.codec.bit_rate) / self.codec.bit_rate > 0.1
        ):
            self.buffer_data = b""
            self.buffer_pts = None
            self.codec = None

        if force_keyframe:
            frame.pict_type = av.video.frame.PictureType.I
        else:
            frame.pict_type = av.video.frame.PictureType.NONE

        if self.codec is None:
            self.codec = av.CodecContext.create("libx264", "w")
            self.codec.width = frame.width
            self.codec.height = frame.height
            self.codec.bit_rate = self.target_bitrate
            self.codec.pix_fmt = "yuv420p"
            self.codec.framerate = fractions.Fraction(FRAME_RATE, 1)
            self.codec.time_base = fractions.Fraction(1, FRAME_RATE)
            bitrate_bps = str(self.target_bitrate)
            self.codec.options = {
                "level": "52",  # 1180x820+ exceeds level 3.1's frame size
                "preset": PRESET,
                "tune": "zerolatency",
                # VBV of 1s: a keyframe/window drag may burst up to the whole
                # buffer. (~2 frames starved keyframes of bits -> blurry.)
                "maxrate": bitrate_bps,
                "bufsize": bitrate_bps,
                "g": str(max(1, round(FRAME_RATE * KEYFRAME_INTERVAL_S))),
            }
            self.codec.profile = "Baseline"

        started = time.perf_counter()
        data_to_send = b"".join(bytes(packet) for packet in self.codec.encode(frame))
        self._record_encode_ms((time.perf_counter() - started) * 1000)

        if data_to_send:
            yield from self._split_bitstream(data_to_send)

    def _record_encode_ms(self, ms: float) -> None:
        self.encode_ms_recent.append(ms)
        if len(self.encode_ms_recent) > 300:
            del self.encode_ms_recent[:150]


def set_target_bitrate(bps: int) -> int:
    """Applies `bps` to every live encoder; returns the clamped value."""
    clamped = max(MIN_BITRATE, min(int(bps), MAX_BITRATE))
    with _lock:
        for encoder in list(_live_encoders):
            encoder.target_bitrate = clamped
    return clamped


def current_target_bitrate() -> int:
    with _lock:
        encoders = list(_live_encoders)
    return encoders[0].target_bitrate if encoders else INITIAL_BITRATE


def drain_encode_ms() -> list[float]:
    with _lock:
        encoders = list(_live_encoders)
    samples: list[float] = []
    for encoder in encoders:
        samples.extend(encoder.encode_ms_recent)
        encoder.encode_ms_recent = []
    return samples


def _get_encoder(codec):
    if codec.mimeType.lower() == "video/h264":
        return TunedH264Encoder()
    return _stock_get_encoder(codec)


def preferred_codecs():
    """Codec list for `setCodecPreferences`: H.264 first, the rest after.

    aiortc's capability list puts VP8 first, and an answerer generally picks
    the first codec it supports from the offer — so without this the stream
    negotiates VP8, which skips the tuned encoder above *and* loses the
    iPad's hardware H.264 decode (libwebrtc decodes VP8 in software on iOS).
    Set VIEWDOCK_VIDEO_CODEC=vp8 to put VP8 first instead.
    """
    from aiortc.codecs import get_capabilities

    codecs = get_capabilities("video").codecs
    first = "video/vp8" if os.environ.get("VIEWDOCK_VIDEO_CODEC", "h264").lower() == "vp8" else "video/h264"
    return sorted(codecs, key=lambda c: 0 if c.mimeType.lower() == first else 1)


def install() -> None:
    aiortc.rtcrtpsender.get_encoder = _get_encoder
    logger.info(
        "H.264 tuning: preset=%s, bitrate %.1f-%.1f Mbps (start %.1f), %d fps, keyframe every %.1fs",
        PRESET, MIN_BITRATE / 1e6, MAX_BITRATE / 1e6, INITIAL_BITRATE / 1e6,
        FRAME_RATE, KEYFRAME_INTERVAL_S,
    )
