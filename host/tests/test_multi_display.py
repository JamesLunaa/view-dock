# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""What several simultaneous virtual monitors need from the X11 layer: unique
mode names, and each monitor placed beside the previous one rather than all
of them landing right of the primary (on top of each other)."""

from unittest.mock import patch

import pytest

from host.config import DisplayConfig
from host.displayserver.x11 import X11DisplayServer

_QUERY = """\
Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 16384 x 16384
eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 344mm x 193mm
HDMI-1 connected (normal left inverted right x axis y axis)
DP-1 connected (normal left inverted right x axis y axis)
"""


@pytest.fixture(autouse=True)
def clean_registry():
    X11DisplayServer._virtual_outputs.clear()
    yield
    X11DisplayServer._virtual_outputs.clear()


def _enable(output: str, calls: list) -> X11DisplayServer:
    def fake_run(args, **kwargs):
        calls.append(args)
        return type("Result", (), {"stdout": _QUERY, "returncode": 0})()

    server = X11DisplayServer()
    with (
        patch("subprocess.run", side_effect=fake_run),
        patch.object(X11DisplayServer, "_build_modeline", return_value=("viewdock_test", ["60.00", "1180"])),
    ):
        server._enable_on(output, DisplayConfig())
    return server


def test_first_virtual_monitor_goes_right_of_the_primary():
    calls: list = []
    _enable("HDMI-1", calls)
    enable = next(c for c in calls if c[:2] == ["xrandr", "--output"] and "--mode" in c)
    assert enable[-2:] == ["--right-of", "eDP-1"]


def test_next_virtual_monitor_goes_right_of_the_previous_one():
    calls: list = []
    _enable("HDMI-1", calls)
    calls.clear()
    _enable("DP-1", calls)
    enable = next(c for c in calls if c[:2] == ["xrandr", "--output"] and "--mode" in c)
    assert enable[-2:] == ["--right-of", "HDMI-1"]


def test_destroying_a_monitor_unregisters_it():
    calls: list = []
    first = _enable("HDMI-1", calls)
    assert X11DisplayServer._virtual_outputs == ["HDMI-1"]
    with patch("subprocess.run"):
        first.destroy_virtual_display()
    assert X11DisplayServer._virtual_outputs == []


def test_mode_names_are_unique_per_display():
    class Result:
        stdout = 'Modeline "x"   68.00  1184 1232 1264 1344  820 823 833 844 +hsync -vsync'

    with patch("subprocess.run", return_value=Result()):
        names = {X11DisplayServer._build_modeline(DisplayConfig())[0] for _ in range(3)}
    assert len(names) == 3
