# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Covers InputInjector's pixel mapping under VIEWDOCK_DISPLAY_SCALE: uinput's
absolute coordinate range, and every emitted x/y, must match the actual X11
screen pixel geometry (DisplayConfig.capture_width/capture_height) — not the
logical point size — since that's the coordinate space the shared pointer
and `host/displayserver/x11.py`'s XRandR mode both live in. `uinput.Device`
isn't instantiated for real here (it creates a live kernel input device); a
fake stands in to record what InputInjector asked for.
"""

from unittest.mock import patch

import uinput

from host.config import DisplayConfig
from host.input.injector import InputInjector


class FakeUinputDevice:
    def __init__(self, events, name=None):
        self.events = events
        self.emitted = []

    def emit(self, event, value, syn=True):
        self.emitted.append((event, value, syn))

    def destroy(self):
        pass


def test_device_absolute_range_matches_capture_pixels_not_logical_points():
    config = DisplayConfig(width=1180, height=820, capture_scale=2)
    with patch("host.input.injector.uinput.Device", FakeUinputDevice):
        injector = InputInjector(config)

    # Each events-list entry is uinput.ABS_X/ABS_Y's (type, code) tuple with
    # (min, max, fuzz, flat) appended — e.g. (3, 0, 0, max, 0, 0).
    abs_x_spec = next(e for e in injector._device.events if e[:2] == uinput.ABS_X)
    abs_y_spec = next(e for e in injector._device.events if e[:2] == uinput.ABS_Y)
    assert abs_x_spec[2:4] == (0, 2360)
    assert abs_y_spec[2:4] == (0, 1640)


def test_handle_input_event_scales_normalized_coords_to_capture_pixels():
    config = DisplayConfig(width=1180, height=820, capture_scale=2)
    with patch("host.input.injector.uinput.Device", FakeUinputDevice):
        injector = InputInjector(config)

    injector.handle_input_event({"kind": "touch_down", "x": 0.5, "y": 0.25})

    emitted_values = {event: value for event, value, _syn in injector._device.emitted}
    assert emitted_values[uinput.ABS_X] == round(0.5 * 2360)
    assert emitted_values[uinput.ABS_Y] == round(0.25 * 1640)
