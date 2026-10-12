# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Minimal client for the xdg-desktop-portal ScreenCast interface, used by the
Wayland display server to have the compositor create a virtual monitor and
hand over its PipeWire stream.

Wayland has no `xrandr`: a client can't create outputs or read the screen
itself. The portal is the sanctioned route — asking for the "virtual" source
type makes the compositor (KWin, via xdg-desktop-portal-kde) create a brand
new monitor that exists only for as long as the session does. The desktop
shows a permission dialog the first time; with `persist_mode` the answer is
remembered through a restore token kept in the user's state directory, so
later sessions start without asking.

Every portal call follows the same Request/Response pattern: the method
returns a request object path immediately, and the real result arrives later
as a `Response` signal on that path. The match rule has to be in place before
the call, or a fast reply can be missed. The D-Bus connection must stay open
for the session's lifetime — the portal ends the session when its owner goes
away.
"""

import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from jeepney import DBusAddress, MatchRule, message_bus, new_method_call
from jeepney.io.blocking import Proxy, open_dbus_connection
from jeepney.wrappers import unwrap_msg

logger = logging.getLogger(__name__)

_PORTAL = DBusAddress(
    "/org/freedesktop/portal/desktop",
    bus_name="org.freedesktop.portal.Desktop",
    interface="org.freedesktop.portal.ScreenCast",
)

SOURCE_VIRTUAL = 4
CURSOR_EMBEDDED = 2
# Remember the permission until the user revokes it, not just for this run.
PERSIST_UNTIL_REVOKED = 2

_RESPONSE_SUCCESS = 0
_RESPONSE_CANCELLED = 1

# Quick calls answer in well under a second; Start may wait on the user
# reading and accepting the permission dialog.
_CALL_TIMEOUT_S = 10.0
_START_TIMEOUT_S = 180.0


class PortalError(RuntimeError):
    pass


@dataclass
class PortalStream:
    node_id: int
    width: int | None
    height: int | None


def restore_token_path() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(state) / "view-dock" / "screencast-restore-token"


def load_restore_token() -> str | None:
    try:
        token = restore_token_path().read_text().strip()
    except OSError:
        return None
    return token or None


def save_restore_token(token: str) -> None:
    path = restore_token_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token)
    except OSError:
        logger.warning("Couldn't save the screen-sharing permission; the desktop will ask again next time.", exc_info=True)


def parse_streams(results: dict) -> list[PortalStream]:
    """Turn Start's `streams` result (a(ua{sv}), values as (signature, value)
    pairs) into PortalStreams."""
    streams = []
    for node_id, props in results.get("streams", ("a(ua{sv})", []))[1]:
        size = props.get("size", ("(ii)", (None, None)))[1]
        streams.append(PortalStream(node_id=node_id, width=size[0], height=size[1]))
    return streams


class ScreenCastPortal:
    """One portal ScreenCast session. Not thread-safe; use from one thread at a time."""

    def __init__(self) -> None:
        self._conn = open_dbus_connection(bus="SESSION", enable_fds=True)
        self._bus = Proxy(message_bus, self._conn)
        # The portal builds request paths from the caller's unique name, ":1.42" -> "1_42".
        self._sender = self._conn.unique_name.lstrip(":").replace(".", "_")
        self._session: str | None = None

    def start_virtual(self, restore_token: str | None) -> tuple[PortalStream, str | None]:
        """Create a session sharing a new virtual monitor. Returns its stream
        and the restore token to use next time (None if the portal gave none)."""
        results = self._request(
            "CreateSession", "a{sv}", (), {"session_handle_token": ("s", self._token())}
        )
        self._session = results["session_handle"][1]

        options = {
            "types": ("u", SOURCE_VIRTUAL),
            "cursor_mode": ("u", CURSOR_EMBEDDED),
            "multiple": ("b", False),
            "persist_mode": ("u", PERSIST_UNTIL_REVOKED),
        }
        if restore_token:
            options["restore_token"] = ("s", restore_token)
        self._request("SelectSources", "oa{sv}", (self._session,), options)

        results = self._request("Start", "osa{sv}", (self._session, ""), {}, timeout=_START_TIMEOUT_S)
        streams = parse_streams(results)
        if not streams:
            raise PortalError("The screen-sharing portal started but returned no stream.")
        token = results.get("restore_token", ("s", None))[1]
        return streams[0], token

    def open_pipewire_remote(self) -> int:
        """A file descriptor on the PipeWire remote that carries the stream.
        The caller owns it."""
        msg = new_method_call(_PORTAL, "OpenPipeWireRemote", "oa{sv}", (self._session, {}))
        (fd,) = unwrap_msg(self._conn.send_and_get_reply(msg, timeout=_CALL_TIMEOUT_S))
        return fd.to_raw_fd()

    def close(self) -> None:
        try:
            if self._session is not None:
                session = DBusAddress(
                    self._session, bus_name=_PORTAL.bus_name, interface="org.freedesktop.portal.Session"
                )
                self._conn.send_and_get_reply(new_method_call(session, "Close"), timeout=_CALL_TIMEOUT_S)
        except Exception:
            logger.debug("Closing the portal session failed; dropping the connection ends it anyway.", exc_info=True)
        finally:
            self._session = None
            self._conn.close()

    @staticmethod
    def _token() -> str:
        return "viewdock_" + secrets.token_hex(8)

    def _request(self, method: str, signature: str, args: tuple, options: dict, timeout: float = _CALL_TIMEOUT_S) -> dict:
        token = self._token()
        path = f"/org/freedesktop/portal/desktop/request/{self._sender}/{token}"
        rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request", member="Response", path=path)
        self._bus.AddMatch(rule)
        try:
            with self._conn.filter(rule) as queue:
                msg = new_method_call(_PORTAL, method, signature, (*args, {**options, "handle_token": ("s", token)}))
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
