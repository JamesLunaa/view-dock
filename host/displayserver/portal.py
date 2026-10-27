# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Minimal client for the xdg-desktop-portal ScreenCast and RemoteDesktop
interfaces, used by the Wayland display servers to have the compositor create
a virtual monitor, hand over its PipeWire stream and, on GNOME, accept input
aimed at it.

Wayland has no `xrandr`: a client can't create outputs or read the screen
itself. The portal is the sanctioned route — asking for the "virtual" source
type makes the compositor (KWin via xdg-desktop-portal-kde, Mutter via
xdg-desktop-portal-gnome) create a brand new monitor that exists only for as
long as the session does. The desktop shows a permission dialog the first
time; with `persist_mode` the answer is remembered through a restore token
kept in the user's state directory, so later sessions start without asking.

A plain ScreenCast session is enough when touches can go through the uinput
touchscreen (KDE maps it onto the output). A RemoteDesktop session adds input
injection on top: pointer events addressed to the stream, so they land on the
virtual monitor whatever its position — needed on GNOME, which has no way to
pin a touchscreen to a virtual monitor.

Every portal call follows the same Request/Response pattern: the method
returns a request object path immediately, and the real result arrives later
as a `Response` signal on that path. The match rule has to be in place before
the call, or a fast reply can be missed. The D-Bus connection must stay open
for the session's lifetime — the portal ends the session when its owner goes
away.

Several clients at once each get their own "slot". The first uses whatever
app id the portal sees for this process; every later one registers its own
(`viewdock-host-2`, ...) on its connection. KDE names the virtual output after
the app id and keeps each output's position and size under that name, so two
sessions with one id would get two outputs that KWin stacks on top of each
other. Each slot also keeps its own restore tokens: a token is good for one
session.
"""

import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from jeepney import DBusAddress, MatchRule, message_bus, new_method_call
from jeepney.io.blocking import Proxy, open_dbus_connection
from jeepney.low_level import MessageFlag
from jeepney.wrappers import unwrap_msg

logger = logging.getLogger(__name__)

_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_PORTAL_BUS = "org.freedesktop.portal.Desktop"
_SCREENCAST = DBusAddress(_PORTAL_PATH, bus_name=_PORTAL_BUS, interface="org.freedesktop.portal.ScreenCast")
_REGISTRY = DBusAddress(_PORTAL_PATH, bus_name=_PORTAL_BUS, interface="org.freedesktop.host.portal.Registry")
_REMOTE_DESKTOP = DBusAddress(_PORTAL_PATH, bus_name=_PORTAL_BUS, interface="org.freedesktop.portal.RemoteDesktop")

SOURCE_VIRTUAL = 4
CURSOR_EMBEDDED = 2
DEVICE_POINTER = 2
# Remember the permission until the user revokes it, not just for this run.
PERSIST_UNTIL_REVOKED = 2
# linux/input-event-codes.h
BTN_LEFT = 0x110

_RESPONSE_SUCCESS = 0
_RESPONSE_CANCELLED = 1

# Quick calls answer in well under a second; Start may wait on the user
# reading and accepting the permission dialog.
_CALL_TIMEOUT_S = 10.0
_START_TIMEOUT_S = 180.0
# The portal notices a newly written desktop file a moment later.
_REGISTER_TIMEOUT_S = 3.0

APP_ID_PREFIX = "viewdock-host"


class PortalError(RuntimeError):
    pass


@dataclass
class PortalStream:
    node_id: int
    width: int | None
    height: int | None


def slot_app_id(slot: int) -> str | None:
    """The app id a slot's sessions register; None for the first slot, which
    keeps the process's own."""
    return None if slot <= 1 else f"{APP_ID_PREFIX}-{slot}"


def restore_token_path(remote_desktop: bool = False, slot: int = 1) -> Path:
    # Separate files: a ScreenCast token isn't valid for a RemoteDesktop session.
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    name = "remotedesktop-restore-token" if remote_desktop else "screencast-restore-token"
    if slot > 1:
        name += f"-{slot}"
    return Path(state) / "view-dock" / name


def load_restore_token(remote_desktop: bool = False, slot: int = 1) -> str | None:
    try:
        token = restore_token_path(remote_desktop, slot).read_text().strip()
    except OSError:
        return None
    return token or None


def save_restore_token(token: str, remote_desktop: bool = False, slot: int = 1) -> None:
    path = restore_token_path(remote_desktop, slot)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token)
    except OSError:
        logger.warning("Couldn't save the screen-sharing permission; the desktop will ask again next time.", exc_info=True)


def desktop_entry_path(app_id: str) -> Path:
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(data) / "applications" / f"{app_id}.desktop"


def ensure_desktop_entry(app_id: str, slot: int) -> None:
    """The portal only accepts an app id that has a desktop file. A hidden one
    is enough; it never shows up in menus."""
    path = desktop_entry_path(app_id)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name=view-dock Host (display {slot})\n"
        "Comment=Lets view-dock give a second device its own virtual display\n"
        "Exec=true\n"
        "NoDisplay=true\n"
    )


def parse_streams(results: dict) -> list[PortalStream]:
    """Turn Start's `streams` result (a(ua{sv}), values as (signature, value)
    pairs) into PortalStreams."""
    streams = []
    for node_id, props in results.get("streams", ("a(ua{sv})", []))[1]:
        size = props.get("size", ("(ii)", (None, None)))[1]
        streams.append(PortalStream(node_id=node_id, width=size[0], height=size[1]))
    return streams


class ScreenCastPortal:
    """One portal session. Session setup and teardown happen on one thread;
    the pointer methods may be called from another while it streams."""

    def __init__(self, app_id: str | None = None) -> None:
        self._conn = open_dbus_connection(bus="SESSION", enable_fds=True)
        self._bus = Proxy(message_bus, self._conn)
        # The portal builds request paths from the caller's unique name, ":1.42" -> "1_42".
        self._sender = self._conn.unique_name.lstrip(":").replace(".", "_")
        self._session: str | None = None
        self._send_lock = threading.Lock()
        if app_id is not None:
            try:
                self._register(app_id)
            except BaseException:
                self._conn.close()
                raise

    def _register(self, app_id: str) -> None:
        # Must come before any other portal call on this connection.
        deadline = time.monotonic() + _REGISTER_TIMEOUT_S
        while True:
            reply = self._conn.send_and_get_reply(
                new_method_call(_REGISTRY, "Register", "sa{sv}", (app_id, {})), timeout=_CALL_TIMEOUT_S
            )
            try:
                unwrap_msg(reply)
                return
            except Exception as exc:
                if time.monotonic() > deadline:
                    raise PortalError(f"The portal wouldn't take the app id {app_id}: {exc}") from exc
            time.sleep(0.2)

    def start_virtual(
        self, restore_token: str | None, remote_desktop: bool = False
    ) -> tuple[PortalStream, str | None]:
        """Create a session sharing a new virtual monitor — with pointer input
        if `remote_desktop`. Returns its stream and the restore token to use
        next time (None if the portal gave none)."""
        session_api = _REMOTE_DESKTOP if remote_desktop else _SCREENCAST
        results = self._request(session_api, "CreateSession", "a{sv}", (), {"session_handle_token": ("s", self._token())})
        self._session = results["session_handle"][1]

        persist = {"persist_mode": ("u", PERSIST_UNTIL_REVOKED)}
        if restore_token:
            persist["restore_token"] = ("s", restore_token)
        sources = {
            "types": ("u", SOURCE_VIRTUAL),
            "cursor_mode": ("u", CURSOR_EMBEDDED),
            "multiple": ("b", False),
        }
        if remote_desktop:
            # In a remote desktop session the permission (and its persistence)
            # belongs to SelectDevices; SelectSources just picks what to share.
            devices = {"types": ("u", DEVICE_POINTER), **persist}
            self._request(_REMOTE_DESKTOP, "SelectDevices", "oa{sv}", (self._session,), devices)
            self._request(_SCREENCAST, "SelectSources", "oa{sv}", (self._session,), sources)
        else:
            self._request(_SCREENCAST, "SelectSources", "oa{sv}", (self._session,), {**sources, **persist})

        results = self._request(session_api, "Start", "osa{sv}", (self._session, ""), {}, timeout=_START_TIMEOUT_S)
        streams = parse_streams(results)
        if not streams:
            raise PortalError("The screen-sharing portal started but returned no stream.")
        if remote_desktop and not results.get("devices", ("u", 0))[1] & DEVICE_POINTER:
            logger.warning("The desktop didn't grant pointer control; touches won't reach the virtual display.")
        token = results.get("restore_token", ("s", None))[1]
        return streams[0], token

    def open_pipewire_remote(self) -> int:
        """A file descriptor on the PipeWire remote that carries the stream.
        The caller owns it."""
        msg = new_method_call(_SCREENCAST, "OpenPipeWireRemote", "oa{sv}", (self._session, {}))
        (fd,) = unwrap_msg(self._conn.send_and_get_reply(msg, timeout=_CALL_TIMEOUT_S))
        return fd.to_raw_fd()

    def pointer_motion_absolute(self, node_id: int, x: float, y: float) -> None:
        """Move the pointer to (x, y) in the stream's logical coordinates."""
        self._notify("NotifyPointerMotionAbsolute", "oa{sv}udd", (node_id, float(x), float(y)))

    def pointer_button(self, button: int, pressed: bool) -> None:
        self._notify("NotifyPointerButton", "oa{sv}iu", (button, 1 if pressed else 0))

    def close(self) -> None:
        try:
            if self._session is not None:
                session = DBusAddress(self._session, bus_name=_PORTAL_BUS, interface="org.freedesktop.portal.Session")
                with self._send_lock:
                    self._conn.send_and_get_reply(new_method_call(session, "Close"), timeout=_CALL_TIMEOUT_S)
        except Exception:
            logger.debug("Closing the portal session failed; dropping the connection ends it anyway.", exc_info=True)
        finally:
            self._session = None
            self._conn.close()

    def _notify(self, method: str, signature: str, args: tuple) -> None:
        # Fire-and-forget: at touch rates a round trip per event would add
        # latency, and replies nobody reads would pile up on the socket.
        if self._session is None:
            return
        msg = new_method_call(_REMOTE_DESKTOP, method, signature, (self._session, {}, *args))
        msg.header.flags |= MessageFlag.no_reply_expected
        with self._send_lock:
            self._conn.send(msg)

    @staticmethod
    def _token() -> str:
        return "viewdock_" + secrets.token_hex(8)

    def _request(
        self, api: DBusAddress, method: str, signature: str, args: tuple, options: dict, timeout: float = _CALL_TIMEOUT_S
    ) -> dict:
        token = self._token()
        path = f"/org/freedesktop/portal/desktop/request/{self._sender}/{token}"
        rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request", member="Response", path=path)
        self._bus.AddMatch(rule)
        try:
            with self._conn.filter(rule) as queue:
                msg = new_method_call(api, method, signature, (*args, {**options, "handle_token": ("s", token)}))
                unwrap_msg(self._conn.send_and_get_reply(msg, timeout=_CALL_TIMEOUT_S))
                signal = self._conn.recv_until_filtered(queue, timeout=timeout)
        finally:
            self._bus.RemoveMatch(rule)

        response, results = signal.body
        if response == _RESPONSE_CANCELLED:
            raise PortalError(f"Screen sharing was declined on the desktop ({method}).")
        if response != _RESPONSE_SUCCESS:
            raise PortalError(f"The screen-sharing portal refused {method} (response {response}).")
        return results
