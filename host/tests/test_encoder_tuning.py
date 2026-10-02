import asyncio
import fractions

import aiortc.rtcrtpsender
import av
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.codecs import h264

from host.config import DisplayConfig
from host.displayserver.base import DisplayServer
from host.streaming import encoder_tuning
from host.streaming.webrtc_session import CaptureVideoTrack, WebRtcSession


def _frame(w=320, h=240, i=0):
    f = av.VideoFrame.from_ndarray(np.random.default_rng(i).integers(0, 255, (h, w, 3), dtype=np.uint8), format="rgb24")
    f.pts = i * 3000
    f.time_base = fractions.Fraction(1, 90000)
    return f


def test_bitrate_clamped_to_tuned_range_not_aiortcs_3mbps():
    enc = encoder_tuning.TunedH264Encoder()
    enc.target_bitrate = 8_000_000
    assert enc.target_bitrate == 8_000_000 > h264.MAX_BITRATE
    enc.target_bitrate = 10
    assert enc.target_bitrate == encoder_tuning.MIN_BITRATE


def test_encoder_produces_h264_and_records_timing():
    enc = encoder_tuning.TunedH264Encoder()
    enc.encode_ms_recent.clear()
    payloads = []
    for i in range(5):
        p, _ = enc.encode(_frame(i=i), force_keyframe=(i == 0))
        payloads += p
    assert payloads and len(enc.encode_ms_recent) == 5


def test_set_target_bitrate_reaches_live_encoders():
    enc = encoder_tuning.TunedH264Encoder()
    assert encoder_tuning.set_target_bitrate(4_000_000) == 4_000_000
    assert enc.target_bitrate == 4_000_000


def test_install_swaps_h264_only():
    encoder_tuning.install()
    from aiortc.codecs import get_capabilities, get_encoder
    from aiortc import RTCRtpCodecParameters

    h = RTCRtpCodecParameters(mimeType="video/H264", clockRate=90000, payloadType=102,
                              parameters={"packetization-mode": "1", "level-asymmetry-allowed": "1", "profile-level-id": "42e01f"})
    v = RTCRtpCodecParameters(mimeType="video/VP8", clockRate=90000, payloadType=96)
    assert isinstance(aiortc.rtcrtpsender.get_encoder(h), encoder_tuning.TunedH264Encoder)
    assert not isinstance(aiortc.rtcrtpsender.get_encoder(v), encoder_tuning.TunedH264Encoder)


def test_h264_is_offered_first_despite_aiortc_listing_vp8_first():
    codecs = encoder_tuning.preferred_codecs()
    assert codecs[0].mimeType == "video/H264"
    assert {c.mimeType for c in codecs} >= {"video/VP8", "video/H264", "video/rtx"}


class _Display(DisplayServer):
    def create_virtual_display(self, config): pass
    def destroy_virtual_display(self): pass
    def capture_frame(self):
        return np.zeros((240, 320, 3), dtype=np.uint8)


def test_track_resyncs_instead_of_bursting_after_a_stall():
    async def run():
        track = CaptureVideoTrack(_Display())
        await track.next_timestamp()
        await asyncio.sleep(0.5)  # simulate a long stall
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        for _ in range(3):
            await track.next_timestamp()
        # aiortc's stock pacing would return these instantly (catching up);
        # resync makes us wait out real frame intervals again.
        return loop.time() - t0

    assert asyncio.run(run()) >= 0.05


def test_loopback_streams_h264_with_tuned_encoder_and_monitor_runs(monkeypatch):
    async def run():
        monkeypatch.setattr("host.streaming.webrtc_session._MONITOR_INTERVAL_S", 0.2)
        session = WebRtcSession(_Display(), type("I", (), {"handle_input_event": lambda s, e: None})(), DisplayConfig())
        viewer = RTCPeerConnection()
        got = asyncio.Event()

        @viewer.on("track")
        def on_track(track):
            async def pull():
                for _ in range(10):
                    await track.recv()
                got.set()
            asyncio.ensure_future(pull())

        class Loop:
            async def send_signal(self, msg):
                await viewer.setRemoteDescription(RTCSessionDescription(**msg))
                await viewer.setLocalDescription(await viewer.createAnswer())
                self.answer = {"sdp": viewer.localDescription.sdp, "type": viewer.localDescription.type}
            async def receive_signal(self):
                return self.answer

        await session.start(Loop())
        await asyncio.wait_for(got.wait(), 20)
        await asyncio.sleep(0.8)
        assert session._monitor_task and not session._monitor_task.done()
        assert session._metrics.fps is not None and session._metrics.bitrate_bps
        assert session._metrics.encode_ms, "monitor should have drained encoder timings"
        assert "H264" in session._pc.localDescription.sdp.split("m=video")[1].split("a=rtpmap")[1]
        await session.close()
        await viewer.close()

    asyncio.run(run())
