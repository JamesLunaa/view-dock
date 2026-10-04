# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Rolling pipeline timings, logged periodically so "it feels laggy" can be
split into capture vs. encode vs. network instead of guessed at.

Host-side only: capture time, frame-to-frame interval (achieved fps), encode
time, RTT, loss. Touch-to-effect latency needs a round-trip message the
protocol doesn't have yet — see TODO.
"""

import logging
import statistics
from collections import deque

logger = logging.getLogger(__name__)

_WINDOW = 300


def _summary(values) -> str:
    if not values:
        return "n/a"
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return f"{statistics.fmean(ordered):.1f}/{p95:.1f}ms"


class PipelineMetrics:
    def __init__(self) -> None:
        self.capture_ms: deque[float] = deque(maxlen=_WINDOW)
        self.convert_ms: deque[float] = deque(maxlen=_WINDOW)
        self.intervals_ms: deque[float] = deque(maxlen=_WINDOW)
        self.encode_ms: deque[float] = deque(maxlen=_WINDOW)
        self.rtt_ms: float | None = None
        self.loss_fraction: float | None = None
        self.bitrate_bps: int | None = None
        self._last_frame_at: float | None = None

    def frame_produced(self, now: float, capture_ms: float, convert_ms: float) -> None:
        self.capture_ms.append(capture_ms)
        self.convert_ms.append(convert_ms)
        if self._last_frame_at is not None:
            self.intervals_ms.append((now - self._last_frame_at) * 1000)
        self._last_frame_at = now

    @property
    def fps(self) -> float | None:
        if not self.intervals_ms:
            return None
        return 1000.0 / statistics.fmean(self.intervals_ms)

    def report(self) -> str:
        fps = self.fps
        return (
            f"fps={fps:.1f} " if fps is not None else "fps=n/a "
        ) + (
            f"capture(avg/p95)={_summary(self.capture_ms)} "
            f"convert={_summary(self.convert_ms)} "
            f"encode={_summary(self.encode_ms)} "
            f"rtt={'n/a' if self.rtt_ms is None else f'{self.rtt_ms:.1f}ms'} "
            f"loss={'n/a' if self.loss_fraction is None else f'{self.loss_fraction * 100:.1f}%'} "
            f"target={'n/a' if self.bitrate_bps is None else f'{self.bitrate_bps / 1e6:.2f}Mbps'}"
        )

    def log(self) -> None:
        logger.info("pipeline: %s", self.report())
