# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Observable host lifecycle, shared by the CLI entrypoint (`main.py`) and
any UI (`host/ui/`) that wants to show connection state instead of a
scrolling log.

The host listens for clients on every transport at once — a Wi-Fi WebSocket
server, plus a tunnel to each USB-attached iPad / Android device — and gives
each admitted client its own virtual monitor, capture, encoder and input
device (up to `max_clients`). A client's monitor is freed when it
disconnects, after a short linger so a dropped-and-reconnected client gets
the same monitor (and the windows on it) back. `request_stop()` gives callers
a clean way to end everything that doesn't depend on SIGINT/SIGTERM.
"""

import asyncio
import enum
import logging
import os
import itertools
from dataclasses import dataclass, field
from typing import Callable

from websockets.exceptions import ConnectionClosed

from host.config import DisplayConfig, HostConfig, max_clients_from_env
from host.displayserver import (
    DisplayServer,
    PassthroughDisplayServer,
    TestPatternDisplayServer,
    X11DisplayServer,
)
from host.input.injector import InputInjector
from host.streaming import WebRtcSession, WiredSession
from host.transport import AdbTransport, Transport, UsbTransport, WifiListener
from host.transport.usb import free_local_port
from protocol import messages

logger = logging.getLogger(__name__)


class State(enum.Enum):
    IDLE = "idle"
    STARTING = "starting"
    WAITING = "waiting for device"
    CONNECTED = "connected"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class StatusEvent:
    state: State
    detail: str = ""
    # Labels of the clients currently streaming (e.g. "Wi-Fi 192.168.1.20").
    clients: tuple[str, ...] = ()


_USB_POLL_S = 1.0
# How long a disconnected client's virtual monitor is kept for it to come back.
_DEFAULT_DISPLAY_LINGER_S = 15.0


def choose_display_server() -> DisplayServer:
    if os.environ.get("VIEWDOCK_TEST_PATTERN_DISPLAY"):
        return TestPatternDisplayServer()
    if os.environ.get("VIEWDOCK_PASSTHROUGH_DISPLAY"):
        return PassthroughDisplayServer()
    return X11DisplayServer()


@dataclass
class _Display:
    """A virtual monitor plus the input device that drives it."""

    server: DisplayServer
    injector: InputInjector
    linger_timer: asyncio.TimerHandle | None = None


@dataclass
class _Client:
    id: int
    label: str
    streaming: bool = False
    task: asyncio.Task | None = field(default=None, repr=False)


class HostRunner:
    """Runs the host and reports its state via `on_status`.

    `on_status` is called from whatever thread/task is driving `run()` — a
    caller handing it to a UI on a different thread (see `host/ui/tui.py`)
    is responsible for marshalling it back to that thread safely.
    """

    def __init__(
        self,
        display_config: DisplayConfig,
        on_status: Callable[[StatusEvent], None] | None = None,
        max_clients: int | None = None,
        wifi_port: int = 8765,
        display_linger_s: float | None = None,
    ) -> None:
        self._display_config = display_config
        self._on_status = on_status or (lambda event: None)
        self._max_clients = max_clients if max_clients is not None else max_clients_from_env()
        self._wifi_port = wifi_port
        self._display_linger_s = (
            display_linger_s
            if display_linger_s is not None
            else float(os.environ.get("VIEWDOCK_DISPLAY_LINGER_S", _DEFAULT_DISPLAY_LINGER_S))
        )
        self._stop_requested = asyncio.Event()
        self._stopping = False
        self._clients: dict[int, _Client] = {}
        self._client_ids = itertools.count(1)
        self._display_ids = itertools.count(1)
        self._parked: list[_Display] = []
        # Display create/destroy talk to the X server and pick "the next free
        # output", so two at once would race for the same one.
        self._display_lock = asyncio.Lock()
        self._usb_tasks: dict[tuple[type, str], asyncio.Task] = {}
        self._config: HostConfig | None = None

    # -- status -------------------------------------------------------------

    def _report(self, state: State, detail: str = "") -> None:
        try:
            self._on_status(
                StatusEvent(state, detail, tuple(c.label for c in self._clients.values() if c.streaming))
            )
        except Exception:
            logger.warning("Status callback raised; ignoring.", exc_info=True)

    def _report_overall(self, note: str = "") -> None:
        streaming = [c.label for c in self._clients.values() if c.streaming]
        if streaming:
            detail = f"{len(streaming)}/{self._max_clients}: {', '.join(streaming)}"
            self._report(State.CONNECTED, f"{detail} — {note}" if note else detail)
        else:
            self._report(State.WAITING, note or "waiting for a device")

    @property
    def client_labels(self) -> list[str]:
        return [c.label for c in self._clients.values() if c.streaming]

    def disconnect_client(self, label: str) -> bool:
        """Ends one client's session by its label. Returns whether one matched."""
        for client in list(self._clients.values()):
            if client.label == label and client.task is not None:
                client.task.cancel()
                return True
        return False

    # -- lifecycle ----------------------------------------------------------

    async def run(self) -> None:
        config = self._config = HostConfig(display=self._display_config, max_clients=self._max_clients)

        cleaned = X11DisplayServer.cleanup_stale_virtual_outputs()
        if cleaned:
            self._report(State.STARTING, f"cleared stale output(s): {', '.join(cleaned)}")

        self._report(State.STARTING, "starting listeners")
        listener = WifiListener(self._wifi_port)
        await listener.start()

        acceptors = [asyncio.ensure_future(self._accept_wifi(listener))]
        if config.prefer_usb:
            acceptors.append(asyncio.ensure_future(self._watch_usb()))
        try:
            self._report_overall(f"Wi-Fi port {self._wifi_port}, USB")
            await self._stop_requested.wait()
        finally:
            self._stopping = True
            self._report(State.STOPPING)
            doomed = [*acceptors, *self._usb_tasks.values(), *(c.task for c in self._clients.values() if c.task)]
            for task in doomed:
                task.cancel()
            await asyncio.gather(*doomed, return_exceptions=True)
            await listener.stop()
            await self._destroy_parked()
            self._report(State.IDLE)

    def request_stop(self) -> None:
        self._stop_requested.set()

    # -- accepting clients --------------------------------------------------

    def _reserve(self, label: str) -> _Client | None:
        """Claims a client slot, or None when the host is full. The slot is held
        from here (before the connection is even usable) so concurrent arrivals
        can't overshoot the cap."""
        if len(self._clients) >= self._max_clients:
            return None
        client = _Client(next(self._client_ids), label)
        self._clients[client.id] = client
        return client

    async def _accept_wifi(self, listener: WifiListener) -> None:
        while True:
            connection = await listener.accept()
            client = self._reserve(connection.label)
            if client is None:
                logger.warning("Refusing %s: the host already has %d clients.", connection.label, self._max_clients)
                self._report_overall(f"refused {connection.label}: host full ({self._max_clients} clients)")
                asyncio.ensure_future(self._refuse(connection))
                continue
            client.task = asyncio.ensure_future(self._serve_client(client, connection))

    @staticmethod
    async def _refuse(transport: Transport) -> None:
        """Tell a client it is not admitted, then hang up. The protocol has no
        dedicated "host full" message; `bye` is what every client already
        handles as "the host ended this connection"."""
        try:
            await transport.send_signal({"type": messages.TYPE_BYE, "reason": "error"})
        except Exception:
            pass
        await transport.disconnect()

    async def _watch_usb(self) -> None:
        """Starts a serving task for every device that appears on a cable, and
        stops it for every device that disappears."""
        while True:
            present: set[tuple[type, str]] = set()
            for transport_class in (UsbTransport, AdbTransport):
                for serial in await transport_class.list_devices():
                    present.add((transport_class, serial))

            for key in present:
                if key not in self._usb_tasks:
                    transport_class, serial = key
                    self._usb_tasks[key] = asyncio.ensure_future(self._serve_usb_device(transport_class, serial))
            for key in list(self._usb_tasks):
                if key not in present:
                    # Unplugged: cancelling ends its session, and an app that was
                    # never reached stops retrying (see `UsbTransport.connect`).
                    self._usb_tasks.pop(key).cancel()
            for key, task in list(self._usb_tasks.items()):
                if task.done():
                    del self._usb_tasks[key]  # crashed; the next poll starts it afresh
            await asyncio.sleep(_USB_POLL_S)

    async def _serve_usb_device(self, transport_class: type[UsbTransport], serial: str) -> None:
        """For one plugged-in device: wait for a free slot, connect through its
        tunnel (retrying until the app is open), serve it, and repeat for as long
        as the cable stays — a closed app that is reopened reconnects by itself."""
        while True:
            transport = transport_class(local_port=free_local_port(), serial=serial)
            client = None
            try:
                while (client := self._reserve(transport.label)) is None:
                    await asyncio.sleep(_USB_POLL_S)  # host full: wait for a client to leave
                client.task = asyncio.current_task()
                await transport.connect()
            except BaseException:
                if client is not None:
                    self._clients.pop(client.id, None)
                await transport.disconnect()
                raise
            await self._serve_client(client, transport)
            await asyncio.sleep(_USB_POLL_S)  # don't spin if the app drops us at once

    # -- serving one client -------------------------------------------------

    async def _serve_client(self, client: _Client, transport: Transport) -> None:
        """Runs one client's session start to finish, then frees everything it
        held. Returns (rather than raising) for ordinary disconnects and errors."""
        assert self._config is not None
        display: _Display | None = None
        session = None
        try:
            self._report_overall(f"{client.label} connecting")
            display = await self._acquire_display(client)

            # A wired transport (Android over adb, a new iPad build over usbmuxd)
            # streams video over its own tunnel; everything else negotiates WebRTC.
            session_class = WiredSession if transport.supports_wired_stream else WebRtcSession
            session = session_class(display.server, display.injector, self._config.display)
            await session.start(transport)

            client.streaming = True
            logger.info("Client connected: %s (%d/%d)", client.label, len(self._clients), self._max_clients)
            self._report_overall()
            await session.wait_closed()
            logger.info("Client disconnected: %s", client.label)
        except asyncio.CancelledError:
            # Stop requested, a per-client disconnect, or the USB device was
            # unplugged. Clean up below, and let the cancellation continue so a
            # device task doesn't go on to reconnect a cable that is gone.
            logger.info("Client session ended: %s", client.label)
            raise
        except ConnectionClosed as error:
            # The device closed the signaling connection before the handshake
            # finished — found live with the Android app: right after a dropped
            # session the host reconnects through the tunnel, and if that lands
            # on the app's about-to-be-recycled listener it gets `1001 going
            # away`. That's "device not ready yet", the same as a disconnect.
            logger.warning("%s closed signaling mid-handshake (%s).", client.label, error)
        except Exception as error:
            # One client failing (e.g. no spare output left for its monitor)
            # must not take the others down.
            logger.exception("Client %s failed", client.label)
            self._report_overall(f"{client.label} failed: {error}")
            try:
                await transport.send_signal({"type": messages.TYPE_BYE, "reason": "error"})
            except Exception:
                pass
        finally:
            client.streaming = False
            if session is not None:
                await session.close()
            await transport.disconnect()
            if display is not None:
                await self._release_display(display)
            self._clients.pop(client.id, None)
            if not self._stopping:
                self._report_overall(f"{client.label} disconnected")

    # -- virtual monitors ---------------------------------------------------

    async def _acquire_display(self, client: _Client) -> _Display:
        """A monitor for `client`: one parked by a client that just left, else a new one."""
        if self._parked:
            display = self._parked.pop()
            if display.linger_timer is not None:
                display.linger_timer.cancel()
                display.linger_timer = None
            logger.info("Reusing a parked virtual display for %s.", client.label)
            return display

        assert self._config is not None
        loop = asyncio.get_running_loop()
        async with self._display_lock:
            server = choose_display_server()
            # xrandr calls and waits for the kernel to re-probe: off the event
            # loop, or every other client's stream stalls while this runs.
            await loop.run_in_executor(None, server.create_virtual_display, self._config.display)
            injector = InputInjector(self._config.display, name=f"view-dock-client-{next(self._display_ids)}")
        return _Display(server, injector)

    async def _release_display(self, display: _Display) -> None:
        if self._stopping or self._display_linger_s <= 0:
            await self._destroy_display(display)
            return
        loop = asyncio.get_running_loop()
        display.linger_timer = loop.call_later(
            self._display_linger_s, lambda: asyncio.ensure_future(self._expire_parked(display))
        )
        self._parked.append(display)

    async def _expire_parked(self, display: _Display) -> None:
        if display in self._parked:
            self._parked.remove(display)
            await self._destroy_display(display)

    async def _destroy_parked(self) -> None:
        while self._parked:
            display = self._parked.pop()
            if display.linger_timer is not None:
                display.linger_timer.cancel()
            await self._destroy_display(display)

    async def _destroy_display(self, display: _Display) -> None:
        loop = asyncio.get_running_loop()
        async with self._display_lock:
            display.injector.close()
            await loop.run_in_executor(None, display.server.destroy_virtual_display)
