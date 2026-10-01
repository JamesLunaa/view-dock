"""Covers the aspect-ratio sanity check for VIEWDOCK_DISPLAY_WIDTH/HEIGHT —
a swapped or mistyped size otherwise letterboxes silently on the iPad with
nothing in the log to explain it — and VIEWDOCK_DISPLAY_SCALE's opt-in
native-pixel capture mode.
"""

import logging

import pytest

from host.config import DisplayConfig, HostConfig, _warn_on_aspect_mismatch


def test_no_warning_for_a_real_ipad_aspect(caplog):
    with caplog.at_level(logging.WARNING):
        _warn_on_aspect_mismatch(1180, 820)  # iPad Air 11" (M2/M3)
    assert caplog.records == []


def test_warns_on_swapped_width_and_height(caplog):
    with caplog.at_level(logging.WARNING):
        _warn_on_aspect_mismatch(820, 1180)  # portrait-shaped mistake
    assert len(caplog.records) == 1
    assert "0.695" in caplog.records[0].message


def test_warns_on_a_non_tablet_aspect_ratio(caplog):
    with caplog.at_level(logging.WARNING):
        _warn_on_aspect_mismatch(1920, 1080)  # 16:9 monitor, pasted by mistake
    assert len(caplog.records) == 1


def test_capture_dimensions_default_to_the_logical_point_size():
    # The off-by-default case: VIEWDOCK_DISPLAY_SCALE unset (capture_scale=1)
    # must leave the actual capture/mode pixel size identical to the
    # logical point size, so nothing changes for the already-verified
    # default setup.
    config = DisplayConfig(width=1180, height=820)
    assert (config.capture_width, config.capture_height) == (1180, 820)


def test_capture_dimensions_scale_up_under_an_explicit_capture_scale():
    config = DisplayConfig(width=1180, height=820, capture_scale=2)
    assert (config.capture_width, config.capture_height) == (2360, 1640)


def test_default_rejects_a_non_positive_display_scale(monkeypatch):
    monkeypatch.setenv("VIEWDOCK_DISPLAY_SCALE", "0")
    with pytest.raises(ValueError):
        HostConfig.default()
