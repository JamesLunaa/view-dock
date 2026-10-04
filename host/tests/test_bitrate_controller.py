# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

from host.streaming.bitrate_controller import BitrateController, NetworkSample

MIN, MAX = 1_000_000, 10_000_000
CLEAN = NetworkSample(rtt_ms=5, loss_fraction=0.0)


def make(initial=6_000_000):
    return BitrateController(MIN, MAX, initial, target_fps=30)


def test_clean_network_probes_upward_to_max():
    c, now = make(), 100.0
    for _ in range(40):
        now += 2.0
        c.update(CLEAN, now)
    assert c.bitrate == MAX


def test_loss_backs_off_multiplicatively():
    c = make()
    new = c.update(NetworkSample(rtt_ms=5, loss_fraction=0.10), 100.0)
    assert new is not None and new < 6_000_000 * 0.75


def test_backoff_has_cooldown_and_floor():
    c = make(initial=MIN * 2)
    lossy = NetworkSample(rtt_ms=5, loss_fraction=0.2)
    assert c.update(lossy, 100.0) is not None
    assert c.update(lossy, 100.5) is None  # inside cooldown
    for i in range(20):
        c.update(lossy, 110.0 + i * 2)
    assert c.bitrate == MIN


def test_no_increase_during_hold_after_decrease():
    c = make()
    c.update(NetworkSample(rtt_ms=5, loss_fraction=0.2), 100.0)
    held = c.bitrate
    assert c.update(CLEAN, 103.0) is None and c.bitrate == held
    assert c.update(CLEAN, 107.0) is not None and c.bitrate > held


def test_rtt_inflation_is_congestion_but_small_jitter_is_not():
    c = make()
    for i in range(5):
        c.update(NetworkSample(rtt_ms=5, loss_fraction=0.0), 100.0 + i * 0.1)
    assert not c.is_congested(NetworkSample(rtt_ms=20))
    assert c.is_congested(NetworkSample(rtt_ms=120))


def test_starved_receiver_fps_is_congestion():
    c = make()
    assert c.is_congested(NetworkSample(fps=12))
    assert not c.is_congested(NetworkSample(fps=29))


def test_missing_signals_are_not_congestion():
    assert not make().is_congested(NetworkSample())
