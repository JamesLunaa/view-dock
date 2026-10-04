"""H.264 encoder for the wired stream: raw Annex-B access units, no RTP.

Settings mirror `encoder_tuning` (baseline profile, zerolatency so there are no
B-frames and decode order equals display order, which the client relies on),
but the bitrate is fixed and much higher: a USB cable has bandwidth to spare,
and desktop text looks much better with it than at WebRTC's adaptive 1-10 Mbps.
"""

import fractions
import os

import av
from av.video.frame import PictureType

from host.streaming import encoder_tuning

WIRED_BITRATE = int(float(os.environ.get("VIEWDOCK_WIRED_BITRATE_MBPS", "20.0")) * 1_000_000)
# Safety net only: over TCP nothing is lost, and each keyframe is a visible
# blur-then-sharpen pulse on static text. Clients can also ask for one.
WIRED_KEYFRAME_INTERVAL_S = float(os.environ.get("VIEWDOCK_WIRED_KEYFRAME_INTERVAL", "10.0"))


class AnnexBEncoder:
    def __init__(self, width: int, height: int, fps: int = encoder_tuning.FRAME_RATE) -> None:
        self._codec = av.CodecContext.create("libx264", "w")
        self._codec.width = width
        self._codec.height = height
        self._codec.pix_fmt = "yuv420p"
        self._codec.framerate = fractions.Fraction(fps, 1)
        self._codec.time_base = fractions.Fraction(1, fps)
        self._codec.bit_rate = WIRED_BITRATE
        bitrate = str(WIRED_BITRATE)
        self._codec.options = {
            "level": "52",
            "preset": encoder_tuning.PRESET,
            "tune": "zerolatency",
            # Half a second of buffer: room for a keyframe burst without
            # starving it (blurry), yet small enough to bound latency.
            "maxrate": bitrate,
            "bufsize": str(WIRED_BITRATE // 2),
            "g": str(max(1, round(fps * WIRED_KEYFRAME_INTERVAL_S))),
        }
        self._codec.profile = "Baseline"

    def encode(self, frame: av.VideoFrame, force_keyframe: bool = False) -> list[tuple[bytes, bool]]:
        """Returns `(annexb_bytes, is_keyframe)` per output packet (normally one)."""
        frame = frame.reformat(format="yuv420p")
        frame.pict_type = PictureType.I if force_keyframe else PictureType.NONE
        return [(bytes(packet), bool(packet.is_keyframe)) for packet in self._codec.encode(frame)]
