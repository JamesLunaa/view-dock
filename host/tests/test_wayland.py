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
import threading
import time
from unittest.mock import patch

import numpy as np
import pytest
from jeepney.low_level import HeaderFields, MessageFlag

from host import runner
from host.config import DisplayConfig
from host.displayserver import pipewire_capture, portal, wayland
from host.displayserver.wayland import GnomeWaylandDisplayServer, KWinWaylandDisplayServer
from host.input.portal_injector import PortalPointerInjector
from protocol import messages


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
        ({"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}, GnomeWaylandDisplayServer),
        ({"XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "GNOME"}, runner.X11DisplayServer),
    ],
)
def test_display_server_follows_the_session_type(env, expected):
    with patch.dict(os.environ, env, clear=True):
        assert isinstance(runner.choose_display_server(), expected)


def test_unsupported_wayland_desktop_says_so():
    env = {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "sway"}
    with patch.dict(os.environ, env, clear=True), pytest.raises(RuntimeError, match="KDE Plasma and GNOME"):
        runner.choose_display_server()


def test_new_output_is_the_one_the_portal_added():
    before = {1, 2}
    outputs = [_output(1, "eDP-1"), _output(2, "HDMI-A-1"), _output(3, "Virtual-Virtual Output")]
    assert wayland.find_new_output(before, outputs)["id"] == 3
    assert wayland.find_new_output(before | {3}, outputs) is None


def test_second_client_output_is_found_despite_sharing_the_first_ones_name():
    # Every portal session from the same app gets the same output name.
    outputs = [_output(1, "eDP-1"), _output(2, "Virtual-virtual-xdp-kde-viewdock-host")]
    outputs.append(_output(3, "Virtual-virtual-xdp-kde-viewdock-host"))
    assert wayland.find_new_output({1, 2}, outputs)["id"] == 3


def test_placement_is_right_of_every_other_screen_in_logical_pixels():
    outputs = [
        _output(1, "eDP-1", width=2880, height=1800, scale=1.5, priority=1),  # 1920 logical
        _output(2, "Virtual-a", x=1920, width=2360, height=1640, scale=2),  # another client's
        _output(3, "Virtual-b"),
        _output(4, "DP-1", x=9999, enabled=False),
    ]
    assert wayland.placement_for(3, outputs) == (1920 + 1180, 0)


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


def test_gnome_pipeline_asks_the_compositor_for_the_device_size_but_kde_does_not():
    gnome = pipewire_capture.build_pipeline(9, 42, 1180, 820, negotiate_size=True)
    kde = pipewire_capture.build_pipeline(9, 42, 1180, 820)
    requested = "video/x-raw,width=1180,height=820"
    # Right after the source, so it drives the negotiation with Mutter.
    assert gnome[gnome.index("pipewiresrc") + 4 : gnome.index("pipewiresrc") + 6] == ["!", requested]
    assert requested not in kde
    assert kde[-5] == "video/x-raw,format=BGRx,width=1180,height=820"


def test_restore_tokens_are_kept_per_session_kind(tmp_path):
    with patch.dict(os.environ, {"XDG_STATE_HOME": str(tmp_path)}):
        portal.save_restore_token("screen", remote_desktop=False)
        portal.save_restore_token("remote", remote_desktop=True)
        assert portal.load_restore_token(remote_desktop=False) == "screen"
        assert portal.load_restore_token(remote_desktop=True) == "remote"


class FakePortal:
    def __init__(self):
        self.calls = []

    def pointer_motion_absolute(self, node_id, x, y):
        self.calls.append(("move", node_id, x, y))

    def pointer_button(self, button, pressed):
        self.calls.append(("button", button, pressed))


def _event(kind, x, y):
    return {"type": "input_event", "kind": kind, "x": x, "y": y, "timestamp_ms": 0}


def test_portal_injector_drags_with_the_left_button_in_stream_pixels():
    fake = FakePortal()
    injector = PortalPointerInjector(fake, 42, DisplayConfig(width=1181, height=821))
    injector.handle_input_event(_event(messages.INPUT_KIND_TOUCH_DOWN, 0.0, 0.0))
    injector.handle_input_event(_event(messages.INPUT_KIND_TOUCH_MOVE, 0.5, 0.5))
    injector.handle_input_event(_event(messages.INPUT_KIND_PENCIL_UP, 1.0, 1.2))
    assert fake.calls == [
        ("move", 42, 0.0, 0.0),
        ("button", portal.BTN_LEFT, True),
        ("move", 42, 590.0, 410.0),
        ("move", 42, 1180.0, 820.0),  # clamped onto the last pixel
        ("button", portal.BTN_LEFT, False),
    ]


def test_gnome_supplies_its_own_injector_and_kde_keeps_uinput():
    gnome = GnomeWaylandDisplayServer()
    gnome._portal, gnome._stream = FakePortal(), portal.PortalStream(node_id=7, width=None, height=None)
    assert isinstance(gnome.create_input_injector(DisplayConfig(), "dev"), PortalPointerInjector)
    assert KWinWaylandDisplayServer().create_input_injector(DisplayConfig(), "dev") is None


def test_pointer_notifications_are_fire_and_forget():
    sent = []

    class FakeConn:
        def send(self, msg):
            sent.append(msg)

    session = portal.ScreenCastPortal.__new__(portal.ScreenCastPortal)
    session._conn, session._session = FakeConn(), "/org/freedesktop/portal/desktop/session/1_2/x"
    session._send_lock = threading.Lock()
    session.pointer_motion_absolute(42, 10, 20.5)
    session.pointer_button(portal.BTN_LEFT, True)

    move, press = sent
    assert move.header.fields[HeaderFields.member] == "NotifyPointerMotionAbsolute"
    assert move.body == (session._session, {}, 42, 10.0, 20.5)
    assert press.body == (session._session, {}, portal.BTN_LEFT, 1)
    assert all(m.header.flags & MessageFlag.no_reply_expected for m in sent)


def test_each_extra_client_gets_its_own_app_id_and_restore_tokens(tmp_path):
    assert portal.slot_app_id(1) is None
    assert portal.slot_app_id(2) == "viewdock-host-2"
    with patch.dict(os.environ, {"XDG_STATE_HOME": str(tmp_path)}):
        portal.save_restore_token("first", slot=1)
        portal.save_restore_token("second", slot=2)
        assert portal.load_restore_token(slot=1) == "first"
        assert portal.load_restore_token(slot=2) == "second"
        assert portal.restore_token_path(slot=1).name == "screencast-restore-token"


def test_slots_are_reused_lowest_first():
    servers = [wayland.KWinWaylandDisplayServer() for _ in range(3)]
    with patch.object(wayland._PortalDisplayServer, "_slots_in_use", set()):
        assert [s._take_slot() for s in servers] == [1, 2, 3]
        servers[0]._free_slot()
        assert wayland.KWinWaylandDisplayServer()._take_slot() == 1


def test_desktop_entry_for_an_extra_slot_is_hidden(tmp_path):
    with patch.dict(os.environ, {"XDG_DATA_HOME": str(tmp_path)}):
        portal.ensure_desktop_entry("viewdock-host-2", 2)
        text = portal.desktop_entry_path("viewdock-host-2").read_text()
    assert "NoDisplay=true" in text
