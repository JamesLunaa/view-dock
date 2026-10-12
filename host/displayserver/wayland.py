# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Wayland implementations of DisplayServer, for KDE Plasma (KWin) and GNOME
(Mutter).

On Wayland only the compositor can create outputs or read the screen, so
each piece the X11 path does by hand goes through the desktop instead. Both
desktops get the monitor and its frames the same way (`_PortalDisplayServer`);
they differ in sizing and input. GNOME is described on its class below; on
KDE:

- The virtual monitor comes from the ScreenCast portal's "virtual" source
  (`portal.py`). KWin creates a real output for it — windows can be placed
  and dragged onto it — that lives exactly as long as the portal session.
- The portal always makes it 1920x1080, so `kscreen-doctor` then adds and
  selects a mode of the device's size, sets its scale and puts it to the
  right of the other screens. Unlike X11, Wayland has per-output scaling, so
  with VIEWDOCK_DISPLAY_SCALE=2 the output runs at the device's full pixel
  resolution while every app renders at the right physical size on it.
- Frames come from the portal's PipeWire stream (`pipewire_capture.py`), with
  the pointer already drawn in by the compositor.
- Touch still goes through the uinput touchscreen (`host/input/injector.py`);
  KWin is told over D-Bus to map that device onto the virtual output, the
  same setting as "Target display" in System Settings > Touchscreen.

KDE needs Plasma 6.6+ (for kscreen-doctor's addCustomMode). Both need
`gst-plugin-pipewire` and `jeepney`.
"""

import json
import logging
import os
import shutil
import subprocess
import time

import numpy as np
from jeepney import DBusAddress, Properties
from jeepney.io.blocking import open_dbus_connection
from jeepney.wrappers import unwrap_msg

from host.config import DisplayConfig
from host.displayserver import portal
from host.displayserver.base import DisplayServer
from host.displayserver.pipewire_capture import PipeWireFrameReader, pipewire_gstreamer_available

logger = logging.getLogger(__name__)

# KWin adds the output a moment after the portal's Start reply.
_OUTPUT_APPEAR_TIMEOUT_S = 5.0
# The uinput device takes a moment to reach KWin after it is created.
_INPUT_DEVICE_TIMEOUT_S = 3.0
_POLL_S = 0.1


def is_wayland_session() -> bool:
    session = os.environ.get("XDG_SESSION_TYPE", "")
    if session:
        return session == "wayland"
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def _desktops() -> list[str]:
    return os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")


def is_gnome_session() -> bool:
    return "GNOME" in _desktops()


def is_kde_session() -> bool:
    return "KDE" in _desktops()


def kscreen_outputs() -> list[dict]:
    result = subprocess.run(["kscreen-doctor", "-j"], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)["outputs"]


def find_new_output(before: set[str], outputs: list[dict]) -> dict | None:
    """The output that wasn't there before the portal started, preferring one
    KWin named as virtual if (unexpectedly) several appeared."""
    new = [o for o in outputs if o["name"] not in before]
    new.sort(key=lambda o: not o["name"].lower().startswith("virtual"))
    return new[0] if new else None


def logical_size(output: dict) -> tuple[float, float]:
    scale = output.get("scale") or 1
    return output["size"]["width"] / scale, output["size"]["height"] / scale


def placement_for(output_name: str, outputs: list[dict]) -> tuple[int, int]:
    """Right of every other enabled screen, top-aligned with the primary one,
    so several clients' monitors line up instead of stacking."""
    others = [o for o in outputs if o.get("enabled") and o["name"] != output_name and o["size"]["width"] > 0]
    if not others:
        return 0, 0
    right = max(o["pos"]["x"] + logical_size(o)[0] for o in others)
    primary = min(others, key=lambda o: o.get("priority") or 1_000_000)
    return round(right), primary["pos"]["y"]


# KWin builds custom modes with CVT, which rounds the width to a multiple of 8
# (1180 -> 1176), so a mode that close counts as the device's size; the few
# pixels' difference is stretched away in capture.
_MODE_WIDTH_TOLERANCE = 8


def find_mode_id(output: dict, width: int, height: int, refresh_hz: int) -> str | None:
    candidates = [
        m
        for m in output.get("modes", [])
        if m["size"]["height"] == height and abs(m["size"]["width"] - width) < _MODE_WIDTH_TOLERANCE
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda m: (abs(m["size"]["width"] - width), abs(m["refreshRate"] - refresh_hz)))["id"]


def map_touch_device_to_output(device_name: str, output_name: str) -> bool:
    """Point KWin's touchscreen mapping for `device_name` at `output_name`.
    False if KWin doesn't list the device (yet)."""
    conn = open_dbus_connection(bus="SESSION")
    try:
        manager = DBusAddress("/org/kde/KWin/InputDevice", "org.kde.KWin", "org.kde.KWin.InputDeviceManager")
        (sys_names,) = unwrap_msg(conn.send_and_get_reply(Properties(manager).get("devicesSysNames")))
        for sys_name in sys_names[1]:
            device = DBusAddress(f"/org/kde/KWin/InputDevice/{sys_name}", "org.kde.KWin", "org.kde.KWin.InputDevice")
            (name,) = unwrap_msg(conn.send_and_get_reply(Properties(device).get("name")))
            if name[1] == device_name:
                unwrap_msg(conn.send_and_get_reply(Properties(device).set("outputName", "s", output_name)))
                return True
        return False
    finally:
        conn.close()


def _require_pipewire_gstreamer() -> None:
    if not pipewire_gstreamer_available():
        raise RuntimeError(
            "GStreamer's PipeWire plugin is missing; install it with `sudo pacman -S gst-plugin-pipewire` "
            "(Debian/Ubuntu: gstreamer1.0-pipewire, Fedora: pipewire-gstreamer)."
        )


class _PortalDisplayServer(DisplayServer):
    """What the Wayland desktops share: a portal session owning the virtual
    monitor, and capture from its PipeWire stream. Ending the session is what
    removes the monitor."""

    supports_bgra_capture = True

    def __init__(self) -> None:
        self._portal: portal.ScreenCastPortal | None = None
        self._reader: PipeWireFrameReader | None = None
        self._stream: portal.PortalStream | None = None

    def _start_portal(self, remote_desktop: bool) -> None:
        self._portal = portal.ScreenCastPortal()
        self._stream, token = self._portal.start_virtual(portal.load_restore_token(remote_desktop), remote_desktop)
        if token:
            portal.save_restore_token(token, remote_desktop)

    def _open_capture(self, config: DisplayConfig, **reader_options) -> None:
        fd = self._portal.open_pipewire_remote()
        try:
            self._reader = PipeWireFrameReader(
                fd, self._stream.node_id, config.capture_width, config.capture_height, **reader_options
            )
        finally:
            os.close(fd)  # the child process holds its own copy

    def capture_frame(self) -> np.ndarray:
        return self.capture_frame_bgra()[:, :, [2, 1, 0]]

    def capture_frame_bgra(self) -> np.ndarray:
        if self._reader is None:
            raise RuntimeError("Display not created; call create_virtual_display() first.")
        return self._reader.latest_bgra()

    def destroy_virtual_display(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None
        if self._portal is not None:
            self._portal.close()
            self._portal = None
        self._stream = None


class GnomeWaylandDisplayServer(_PortalDisplayServer):
    """GNOME (Mutter). The virtual monitor comes from a RemoteDesktop portal
    session with a virtual screen-cast source; Mutter sizes it from the
    stream's negotiated format, so asking for the device's size in the
    capture pipeline is all the setup it needs. Touches go through the same
    session as pointer events aimed at the stream (`PortalPointerInjector`):
    GNOME can only pin a touchscreen to a monitor with an EDID, which a
    virtual one doesn't have."""

    def create_virtual_display(self, config: DisplayConfig) -> None:
        _require_pipewire_gstreamer()
        try:
            self._start_portal(remote_desktop=True)
            self._open_capture(config, negotiate_size=True)
        except BaseException:
            self.destroy_virtual_display()
            raise
        logger.info("Virtual display created through the remote-desktop portal.")

    def create_input_injector(self, config: DisplayConfig, device_name: str):
        from host.input.portal_injector import PortalPointerInjector

        return PortalPointerInjector(self._portal, self._stream.node_id, config)


class KWinWaylandDisplayServer(_PortalDisplayServer):
    def __init__(self) -> None:
        super().__init__()
        self._output_name: str | None = None

    def create_virtual_display(self, config: DisplayConfig) -> None:
        self._check_prerequisites()
        before = {o["name"] for o in kscreen_outputs()}
        try:
            self._start_portal(remote_desktop=False)
            output = self._wait_for_output(before)
            self._output_name = output["name"]
            sized = self._configure_output(output, config)
            self._open_capture(config, letterbox=not sized)
        except BaseException:
            self.destroy_virtual_display()
            raise
        logger.info("Virtual display %s created through the screen-cast portal.", self._output_name)

    def attach_input_device(self, device_name: str) -> None:
        if self._output_name is None:
            return
        deadline = time.monotonic() + _INPUT_DEVICE_TIMEOUT_S
        try:
            while not map_touch_device_to_output(device_name, self._output_name):
                if time.monotonic() > deadline:
                    logger.warning("KWin doesn't list input device %s; touches may land on the wrong screen.", device_name)
                    return
                time.sleep(_POLL_S)
        except Exception:
            logger.warning("Couldn't map touch input onto %s; touches may land on the wrong screen.", self._output_name, exc_info=True)

    def destroy_virtual_display(self) -> None:
        super().destroy_virtual_display()
        self._output_name = None

    @staticmethod
    def _check_prerequisites() -> None:
        if shutil.which("kscreen-doctor") is None:
            raise RuntimeError("kscreen-doctor not found; install kscreen (part of KDE Plasma).")
        _require_pipewire_gstreamer()

    @staticmethod
    def _wait_for_output(before: set[str]) -> dict:
        deadline = time.monotonic() + _OUTPUT_APPEAR_TIMEOUT_S
        while True:
            output = find_new_output(before, kscreen_outputs())
            if output is not None:
                return output
            if time.monotonic() > deadline:
                raise RuntimeError("The portal started, but no new output appeared in KWin.")
            time.sleep(_POLL_S)

    @staticmethod
    def _configure_output(output: dict, config: DisplayConfig) -> bool:
        """Size, scale and place the output. False if it couldn't be given a
        mode of the device's size (so capture should letterbox, not stretch)."""
        # Address the output by id: the portal's output names can contain spaces.
        oid = output["id"]
        width, height = config.capture_width, config.capture_height
        mode_id = find_mode_id(output, width, height, config.refresh_hz)
        if mode_id is None:
            add = f"output.{oid}.addCustomMode.{width}.{height}.{config.refresh_hz * 1000}.full"
            result = subprocess.run(["kscreen-doctor", add], capture_output=True, text=True)
            if result.returncode != 0:
                logger.warning("kscreen-doctor couldn't add a %dx%d mode: %s", width, height, result.stderr.strip())
            output = next(o for o in kscreen_outputs() if o["id"] == oid)
            mode_id = find_mode_id(output, width, height, config.refresh_hz)

        settings = [f"output.{oid}.scale.{config.capture_scale}"]
        if mode_id is None:
            logger.warning(
                "No %dx%d mode on the virtual output (Plasma 6.6+ is needed to add one); "
                "the picture will be letterboxed.",
                width,
                height,
            )
        else:
            settings.append(f"output.{oid}.mode.{mode_id}")
        x, y = placement_for(output["name"], kscreen_outputs())
        settings.append(f"output.{oid}.position.{x},{y}")
        result = subprocess.run(["kscreen-doctor", *settings], capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning("kscreen-doctor couldn't configure the virtual output: %s", result.stderr.strip())
        return mode_id is not None
