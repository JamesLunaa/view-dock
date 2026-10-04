# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Pure-math tests for X11DisplayServer._exact_width_modeline — the fix for
`cvt -r`'s multiple-of-8 width rounding (1180 -> 1184) that otherwise left
the stream ~0.3% off the panel's aspect ratio (a hairline letterbox on the
iPad's aspect-fit). No real `cvt`/xrandr involved: these are canned
`cvt -r` outputs, so they run in CI/headless environments.
"""

from unittest.mock import patch

from host.config import DisplayConfig
from host.displayserver.x11 import X11DisplayServer

# `cvt -r 1184 820 60` real output.
_CVT_1184x820 = "68.00 1184 1232 1264 1344 820 823 833 844 +hsync -vsync".split()


def test_exact_width_noop_when_already_exact():
    assert X11DisplayServer._exact_width_modeline(_CVT_1184x820, 1184) == _CVT_1184x820


def test_exact_width_shrinks_active_and_sync_timings_by_delta():
    result = X11DisplayServer._exact_width_modeline(_CVT_1184x820, 1180)

    # delta = 1184 - 1180 = 4, subtracted from every horizontal figure.
    assert result[1:5] == ["1180", "1228", "1260", "1340"]
    # Vertical timing and flags are untouched.
    assert result[5:] == ["820", "823", "833", "844", "+hsync", "-vsync"]


def test_exact_width_preserves_blanking_width():
    result = X11DisplayServer._exact_width_modeline(_CVT_1184x820, 1180)
    hdisp, hss, hse, htotal = (int(v) for v in result[1:5])

    front_porch, sync_width, back_porch = hss - hdisp, hse - hss, htotal - hse
    assert (front_porch, sync_width, back_porch) == (48, 32, 80)


def test_exact_width_rescales_pixel_clock_to_hold_refresh():
    result = X11DisplayServer._exact_width_modeline(_CVT_1184x820, 1180)

    # cvt -r 1184 820 60 is itself only ~59.95Hz (CVT's own rounding), not an
    # exact 60 — what matters is the narrower mode holds *that* refresh
    # rather than drifting it, within the precision lost by rounding the
    # pixel clock to 2 decimals (same precision `cvt` itself emits).
    original_pclk, original_htotal, vtotal = 68.00, 1344, 844
    original_refresh = original_pclk * 1_000_000 / (original_htotal * vtotal)

    new_pclk, new_htotal = float(result[0]), 1340
    new_refresh = new_pclk * 1_000_000 / (new_htotal * vtotal)

    assert abs(new_refresh - original_refresh) < 0.01


def test_build_modeline_uses_capture_pixels_not_logical_points_under_scale():
    """VIEWDOCK_DISPLAY_SCALE (DisplayConfig.capture_scale) must drive the
    actual XRandR mode `cvt` is asked to build — this is the real display
    mss captures, so it has to be the scaled-up pixel size, not the
    logical point size `width`/`height` still describe."""
    config = DisplayConfig(width=1180, height=820, refresh_hz=60, capture_scale=2)
    cvt_calls = []

    def fake_run(args, **kwargs):
        if args[0] == "cvt":
            cvt_calls.append(args)
            return type(
                "Result",
                (),
                {"stdout": 'Modeline "2360x1640_60.00"   137.75  2360 2456 2696 2928  1640 1643 1653 1689 -hsync +vsync'},
            )()
        raise AssertionError(f"unexpected subprocess call: {args}")

    with patch("subprocess.run", side_effect=fake_run):
        mode_name, modeline = X11DisplayServer._build_modeline(config)

    assert cvt_calls == [["cvt", "-r", "2360", "1640", "60"]]
    assert mode_name.startswith("viewdock_2360x1640_60_")
    assert modeline[1] == "2360"  # exact-width patch is a no-op: cvt didn't round 2360
