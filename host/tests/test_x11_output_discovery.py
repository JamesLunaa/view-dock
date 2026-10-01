"""Pure parsing-logic tests for displayserver/x11.py's xrandr-output helpers,
added alongside host/ui/ (which relies on these for its pre-flight check and
stale-mode cleanup) — these run against canned `xrandr --query` text rather
than a real X server, so they're safe in CI/headless environments.
"""

from unittest.mock import patch

from host.displayserver.x11 import X11DisplayServer

_QUERY_WITH_STALE_MODE = """\
Screen 0: minimum 320 x 200, current 3100 x 1640, maximum 16384 x 16384
eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 344mm x 193mm
   1920x1080     60.00*+
HDMI-A-1 connected 1180x820+1920+0 (normal left inverted right x axis y axis) 0mm x 0mm
   viewdock_1180x820_60_99999 60.00*+
DP-1 disconnected (normal left inverted right x axis y axis)
"""

_QUERY_NO_STALE_MODE = """\
Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 16384 x 16384
eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 344mm x 193mm
   1920x1080     60.00*+
HDMI-A-1 connected (normal left inverted right x axis y axis)
DP-1 disconnected (normal left inverted right x axis y axis)
"""


def _run_side_effect(stdout: str):
    def _run(args, **kwargs):
        if args[:2] == ["xrandr", "--query"]:
            return type("Result", (), {"stdout": stdout})()
        return type("Result", (), {"stdout": ""})()

    return _run


def test_list_disconnected_outputs_finds_only_disconnected():
    with patch("subprocess.run", side_effect=_run_side_effect(_QUERY_WITH_STALE_MODE)):
        assert X11DisplayServer.list_disconnected_outputs() == ["DP-1"]


def test_cleanup_stale_virtual_outputs_tears_down_leftover_mode():
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["xrandr", "--query"]:
            return type("Result", (), {"stdout": _QUERY_WITH_STALE_MODE})()
        return type("Result", (), {"returncode": 0})()

    with patch("subprocess.run", side_effect=fake_run):
        cleaned = X11DisplayServer.cleanup_stale_virtual_outputs()

    assert cleaned == ["viewdock_1180x820_60_99999"]
    assert ["xrandr", "--output", "HDMI-A-1", "--off"] in calls
    assert ["xrandr", "--delmode", "HDMI-A-1", "viewdock_1180x820_60_99999"] in calls
    assert ["xrandr", "--rmmode", "viewdock_1180x820_60_99999"] in calls


def test_cleanup_stale_virtual_outputs_noop_when_clean():
    with patch("subprocess.run", side_effect=_run_side_effect(_QUERY_NO_STALE_MODE)):
        assert X11DisplayServer.cleanup_stale_virtual_outputs() == []


def test_find_available_output_keys_on_missing_geometry():
    with patch("subprocess.run", side_effect=_run_side_effect(_QUERY_NO_STALE_MODE)):
        assert X11DisplayServer.find_available_output() == "HDMI-A-1"
