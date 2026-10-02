"""Adaptive bitrate: turns network samples into a target encoder bitrate.

Pure logic with no aiortc dependency, so it's unit-testable with a fake
clock. Loss-and-delay AIMD: back off multiplicatively the moment the path
looks congested, probe upward slowly once it's been clean for a while.

Samples come from the host's own RTCP receiver reports (RTT + fraction
lost) — the iPad app doesn't send `stats` messages yet — plus the iPad's
received `fps` whenever a `stats` message does arrive.
"""

from dataclasses import dataclass

# Congestion thresholds.
LOSS_BACKOFF = 0.03        # >3% packets lost over the last report interval
RTT_INFLATION_MS = 40.0    # RTT this far above the best seen = queues filling
RTT_INFLATION_RATIO = 2.0  # ...or this many times the best seen
FPS_STARVED_RATIO = 0.7    # receiver rendering <70% of the target frame rate

DECREASE_FACTOR = 0.75
MAX_LOSS_DECREASE = 0.5    # never cut more than half in one step
INCREASE_FACTOR = 1.2      # >10%: aiortc only re-tunes x264 past that margin
DECREASE_COOLDOWN_S = 1.5
INCREASE_INTERVAL_S = 2.0
HOLD_AFTER_DECREASE_S = 6.0
RTT_WINDOW = 30            # samples the "best RTT" baseline is taken over


@dataclass
class NetworkSample:
    rtt_ms: float | None = None
    loss_fraction: float | None = None  # 0.0-1.0
    fps: float | None = None            # frames/s the receiver actually got


class BitrateController:
    def __init__(self, min_bps: int, max_bps: int, initial_bps: int, target_fps: float = 30.0) -> None:
        self._min = min_bps
        self._max = max_bps
        self._target_fps = target_fps
        self.bitrate = max(min_bps, min(initial_bps, max_bps))
        self._rtts: list[float] = []
        self._last_decrease = float("-inf")
        self._last_increase = float("-inf")

    def is_congested(self, sample: NetworkSample) -> bool:
        if sample.loss_fraction is not None and sample.loss_fraction > LOSS_BACKOFF:
            return True
        if sample.fps is not None and sample.fps < self._target_fps * FPS_STARVED_RATIO:
            return True
        if sample.rtt_ms is not None and self._rtts:
            best = min(self._rtts)
            if sample.rtt_ms > best + RTT_INFLATION_MS and sample.rtt_ms > best * RTT_INFLATION_RATIO:
                return True
        return False

    def update(self, sample: NetworkSample, now: float) -> int | None:
        """Returns the new target bitrate if it changed, else None."""
        congested = self.is_congested(sample)
        if sample.rtt_ms is not None:
            self._rtts.append(sample.rtt_ms)
            del self._rtts[:-RTT_WINDOW]

        previous = self.bitrate
        if congested:
            if now - self._last_decrease >= DECREASE_COOLDOWN_S:
                loss = sample.loss_fraction or 0.0
                factor = max(1.0 - loss, MAX_LOSS_DECREASE) if loss > LOSS_BACKOFF else 1.0
                self.bitrate = max(self._min, int(self.bitrate * DECREASE_FACTOR * factor))
                self._last_decrease = now
        elif (
            now - self._last_decrease >= HOLD_AFTER_DECREASE_S
            and now - self._last_increase >= INCREASE_INTERVAL_S
        ):
            self.bitrate = min(self._max, int(self.bitrate * INCREASE_FACTOR))
            self._last_increase = now

        return self.bitrate if self.bitrate != previous else None
