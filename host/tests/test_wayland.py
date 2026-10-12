# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""The KDE Wayland display server's pure logic: picking it for a Wayland
session, finding the output the portal created, sizing and placing it with
kscreen-doctor, reading the portal's stream list, keeping the restore token,
and the PipeWire frame reader's byte-to-frame handling. Nothing here talks to
a real compositor, portal or PipeWire; a small Python child stands in for
gst-launch-1.0.
"""

import os
import subprocess
import sys
import time
from unittest.mock import patch

import numpy as np
import pytest

from host import runner
from host.config import DisplayConfig
from host.displayserver import pipewire_capture, portal, wayland
from host.displayserver.wayland import KWinWaylandDisplayServer


def _output(oid, name, x=0, width=1920, height=1080, scale=1, enabled=True, priority=0, modes=()):
    return {
        "id": oid,
        "name": name,
        "enabled": enabled,
        "pos": {"x": x, "y": 0},
        "size": {"width": width, "height": height},
        "scale": scale,
        "priority": priority,
        "modes": [
            {"id": mid, "size": {"width": w, "height": h}, "refreshRate": r} for mid, w, h, r in modes
        ],
    }


@pytest.mark.parametrize(
    "env, expected",
    [
        ({"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"}, KWinWaylandDisplayServer),
        ({"XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "KDE", "WAYLAND_DISPLAY": "wayland-0"}, runner.X11DisplayServer),
        ({"WAYLAND_DISPLAY": "wayland-0", "XDG_CURRENT_DESKTOP": "ubuntu:KDE"}, KWinWaylandDisplayServer),
    ],
)
def test_display_server_follows_the_session_type(env, expected):
    with patch.dict(os.environ, env, clear=True):
        assert isinstance(runner.choose_display_server(), expected)


def test_unsupported_wayland_desktop_says_so():
    env = {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "GNOME"}
    with patch.dict(os.environ, env, clear=True), pytest.raises(RuntimeError, match="KDE Plasma"):
        runner.choose_display_server()


def test_new_output_is_the_one_the_portal_added():
    before = {"eDP-1", "HDMI-A-1"}
    outputs = [_output(1, "eDP-1"), _output(2, "HDMI-A-1"), _output(3, "Virtual-Virtual Output")]
    assert wayland.find_new_output(before, outputs)["id"] == 3
    assert wayland.find_new_output(before | {"Virtual-Virtual Output"}, outputs) is None


def test_placement_is_right_of_every_other_screen_in_logical_pixels():
    outputs = [
        _output(1, "eDP-1", width=2880, height=1800, scale=1.5, priority=1),  # 1920 logical
        _output(2, "Virtual-a", x=1920, width=2360, height=1640, scale=2),  # another client's
        _output(3, "Virtual-b"),
        _output(4, "DP-1", x=9999, enabled=False),
    ]
    assert wayland.placement_for("Virtual-b", outputs) == (1920 + 1180, 0)


def test_mode_lookup_prefers_the_closest_refresh_rate():
    output = _output(5, "Virtual", modes=[("a", 1920, 1080, 60.0), ("b", 1180, 820, 30.0), ("c", 1180, 820, 59.9)])
    assert wayland.find_mode_id(output, 1180, 820, 60) == "c"
    assert wayland.find_mode_id(output, 2360, 1640, 60) is None


def test_mode_lookup_accepts_cvts_width_rounding():
    # Asking KWin for 1180x820 yields 1176x820 (CVT rounds width to a multiple of 8).
    output = _output(5, "Virtual", modes=[("a", 1920, 1080, 60.0), ("b", 1176, 820, 59.86), ("c", 1168, 820, 60.0)])
    assert wayland.find_mode_id(output, 1180, 820, 60) == "b"
    assert wayland.find_mode_id(output, 1190, 820, 60) is None


def test_configure_adds_the_device_mode_then_applies_mode_scale_and_position():
    virtual = _output(7, "Virtual-Virtual Output", modes=[("1", 1920, 1080, 60.0)])
    with_mode = _output(7, "Virtual-Virtual Output", modes=[("1", 1920, 1080, 60.0), ("2", 2360, 1640, 60.0)])
    primary = _output(1, "eDP-1", priority=1)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    config = DisplayConfig(width=1180, height=820, refresh_hz=60, capture_scale=2)
    with patch.object(wayland.subprocess, "run", fake_run), patch.object(
        wayland, "kscreen_outputs", return_value=[primary, with_mode]
    ):
        assert KWinWaylandDisplayServer._configure_output(virtual, config)

    assert calls == [
        ["kscreen-doctor", "output.7.addCustomMode.2360.1640.60000.full"],
        ["kscreen-doctor", "output.7.scale.2", "output.7.mode.2", "output.7.position.1920,0"],
    ]


def test_start_response_streams_are_parsed():
    results = {"streams": ("a(ua{sv})", [(42, {"size": ("(ii)", (1920, 1080)), "source_type": ("u", 4)})])}
    assert portal.parse_streams(results) == [portal.PortalStream(node_id=42, width=1920, height=1080)]
    assert portal.parse_streams({}) == []


def test_restore_token_round_trips_through_the_state_dir(tmp_path):
    with patch.dict(os.environ, {"XDG_STATE_HOME": str(tmp_path)}):
        assert portal.load_restore_token() is None
        portal.save_restore_token("abc-123")
        assert portal.load_restore_token() == "abc-123"
        assert portal.restore_token_path() == tmp_path / "view-dock" / "screencast-restore-token"


def test_frame_reader_publishes_whole_frames_and_keeps_the_latest():
    width, height = 4, 2
    frame_bytes = width * height * 4
    # Two frames, a beat apart, written in awkward chunks to exercise short reads.
    script = (
        "import sys, time\n"
        "for value in (1, 2):\n"
        f"    data = bytes([value]) * {frame_bytes}\n"
        "    for i in range(0, len(data), 5):\n"
        "        sys.stdout.buffer.write(data[i:i+5]); sys.stdout.buffer.flush()\n"
        "    time.sleep(0.5)\n"
        "time.sleep(5)\n"
    )
    read_fd, write_fd = os.pipe()
    try:
        with patch.object(pipewire_capture, "build_pipeline", return_value=[sys.executable, "-c", script]):
            reader = pipewire_capture.PipeWireFrameReader(read_fd, 1, width, height)
        try:
            first = reader.latest_bgra()
            assert (first == 1).all()
            assert first.shape == (height, width, 4) and first.dtype == np.uint8
            for _ in range(100):
                if reader.latest_bgra()[0, 0, 0] == 2:
                    break
                time.sleep(0.02)
            latest = reader.latest_bgra()
            assert (latest == 2).all()
            assert first is not latest  # published frames are never overwritten
        finally:
            reader.close()
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_frame_reader_reports_why_the_stream_died():
    script = "import sys; sys.stderr.write('no such node\\n')"
    read_fd, write_fd = os.pipe()
    try:
        with patch.object(pipewire_capture, "build_pipeline", return_value=[sys.executable, "-c", script]), patch.object(
            pipewire_capture, "_FIRST_FRAME_TIMEOUT_S", 0.5
        ):
            reader = pipewire_capture.PipeWireFrameReader(read_fd, 1, 4, 2)
            with pytest.raises(RuntimeError, match="no such node"):
                reader.latest_bgra()
            reader.close()
    finally:
        os.close(read_fd)
        os.close(write_fd)
