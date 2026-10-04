# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Observable host session lifecycle, shared by the CLI entrypoint
(`main.py`) and any UI (`host/ui/`) that wants to show connection state
instead of a scrolling log.

This is the same sequence `main.py` used to run inline: pick a transport,
bring up the virtual display, run the WebRTC session until it closes or a
stop is requested, then tear everything down. Pulling it out means a UI can
drive it without reimplementing that sequence, and `request_stop()` gives
callers a clean way to end a session that doesn't depend on SIGINT/SIGTERM.
"""

import asyncio
import enum
import logging
import os
from dataclasses import dataclass
from typing import Callable

from websockets.exceptions import ConnectionClosed

from host.config import DisplayConfig, HostConfig
from host.displayserver import (
    DisplayServer,
    PassthroughDisplayServer,
    TestPatternDisplayServer,
    X11DisplayServer,
)
from host.input.injector import InputInjector
from host.streaming import WebRtcSession, WiredSession
from host.transport import AdbTransport, UsbTransport, WifiTransport

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


async def _find_wired_transport() -> UsbTransport | None:
    """First wired transport with a device attached: usbmuxd for an iPad,
    then `adb` for an Android device. `AdbTransport` is a `UsbTransport`
    subclass, so everything downstream that only cares "is this a cable?"
    can keep checking `isinstance(transport, UsbTransport)`."""
    for transport_class in (UsbTransport, AdbTransport):
        transport = transport_class()
        if await transport.is_available():
            return transport
    return None


async def choose_transport(config: HostConfig):
    if config.prefer_usb:
        wired = await _find_wired_transport()
        if wired is not None:
            return wired
    return WifiTransport()


async def _wait_until_usb_available(poll_interval: float = 1.0) -> None:
    """Polls until a USB-attached iPad or Android device shows up. Used to
    let a session that fell back to Wi-Fi (no device plugged in yet when it
    started) switch to USB the moment a cable appears, instead of only
    checking once at startup and then ignoring USB for the rest of the
    session."""
    while await _find_wired_transport() is None:
        await asyncio.sleep(poll_interval)


async def _wait_until_usb_unavailable(poll_interval: float = 1.0) -> None:
    """Polls until a USB-attached iPad or Android device disappears.

    Found live: WebRTC's ICE can keep a connection's actual video/data
    flowing over Wi-Fi even after the USB cable is unplugged, if the iPad
    happens to share a LAN with this host — ICE just uses whatever
    candidate pair is reachable, independent of which transport carried the
    signaling, so nothing about unplugging the cable necessarily breaks the
    negotiated path. That's arguably a nice feature on its own, but someone
    who explicitly connected over USB may want unplugging it to always mean
    "disconnected" rather than a silent continue-over-Wi-Fi. Used to force
    that the moment the device physically disappears, instead of waiting on
    (or never getting) a WebRTC-level failure.
    """
    while await _find_wired_transport() is not None:
        await asyncio.sleep(poll_interval)


def choose_display_server() -> DisplayServer:
    if os.environ.get("VIEWDOCK_TEST_PATTERN_DISPLAY"):
        return TestPatternDisplayServer()
    if os.environ.get("VIEWDOCK_PASSTHROUGH_DISPLAY"):
        return PassthroughDisplayServer()
    return X11DisplayServer()


class HostRunner:
    """Runs one host session and reports its state via `on_status`.

    `on_status` is called from whatever thread/task is driving `run()` — a
    caller handing it to a UI on a different thread (see `host/ui/tui.py`)
    is responsible for marshalling it back to that thread safely.
    """

    def __init__(
        self,
        display_config: DisplayConfig,
        on_status: Callable[[StatusEvent], None] | None = None,
    ) -> None:
        self._display_config = display_config
        self._on_status = on_status or (lambda event: None)
        self._stop_requested = asyncio.Event()

    def _report(self, state: State, detail: str = "") -> None:
        try:
            self._on_status(StatusEvent(state, detail))
        except Exception:
            logger.warning("Status callback raised; ignoring.", exc_info=True)

    async def _establish_transport(self, config: HostConfig):
        """Picks a transport and waits for it to connect, switching from
        Wi-Fi to USB mid-wait if a cable shows up (see the comment below).

        Returns `(transport, transport_name)` once connected, or `None` if a
        stop was requested first — in which case this has already run the
        same disconnect/IDLE cleanup `run()`'s own stop path would, so the
        caller should just return.
        """
        self._report(State.STARTING, "choosing transport")
        transport = await choose_transport(config)
        transport_name = type(transport).__name__

        # For both transports, connect() is the part that actually blocks
        # waiting on the iPad (WifiTransport until a client connects,
        # UsbTransport retrying the iproxy tunnel) — report it as such rather
        # than leaving the status stuck on "choosing transport" the whole
        # time. It can block indefinitely (no iPad ever shows up), so race it
        # against a stop request too — otherwise request_stop() before a
        # connection exists does nothing, since nothing is awaiting the
        # _stop_requested event yet.
        #
        # choose_transport() only checks for USB once, at the top of this
        # method — if no iPad was plugged in yet at that moment, it falls
        # back to Wi-Fi and never reconsiders USB for the rest of the
        # session, even if a cable shows up moments later while still
        # waiting. Found live: plugging in mid-wait just did nothing until
        # the whole session was restarted. So: while waiting on a Wi-Fi
        # connect, also poll for USB and switch over if it appears.
        while True:
            self._report(State.WAITING, f"connecting via {transport_name}")
            connect_task = asyncio.ensure_future(transport.connect())
            stop_task = asyncio.ensure_future(self._stop_requested.wait())
            waitables = {connect_task, stop_task}

            watch_usb_task = None
            if config.prefer_usb and isinstance(transport, WifiTransport):
                watch_usb_task = asyncio.ensure_future(_wait_until_usb_available())
                waitables.add(watch_usb_task)

            done, pending = await asyncio.wait(waitables, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

            if stop_task in done:
                self._report(State.STOPPING)
                await transport.disconnect()
                self._report(State.IDLE)
                return None

            if watch_usb_task is not None and watch_usb_task in done:
                self._report(State.STARTING, "USB connected; switching from Wi-Fi")
                await transport.disconnect()
                # The cable that triggered the switch could vanish again before
                # this re-check; fall back to the iPad transport rather than
                # crash — its own connect() retries until a device appears.
                transport = await _find_wired_transport() or UsbTransport()
                transport_name = type(transport).__name__
                continue

            try:
                connect_task.result()
            except Exception:
                # Found live: a transport whose connect() exhausts its own
                # retries and raises (e.g. UsbTransport's iproxy tunnel never
                # came up) left its iproxy subprocess running, since nothing
                # called disconnect() on the way out — the next attempt then
                # failed immediately with "Address already in use" on top of
                # the original error.
                await transport.disconnect()
                raise
            return transport, transport_name

    async def run(self) -> None:
        config = HostConfig(display=self._display_config)

        cleaned = X11DisplayServer.cleanup_stale_virtual_outputs()
        if cleaned:
            self._report(State.STARTING, f"cleared stale output(s): {', '.join(cleaned)}")

        established = await self._establish_transport(config)
        if established is None:
            return
        transport, transport_name = established

        self._report(State.STARTING, "bringing up virtual display")
        display_server = choose_display_server()
        display_server.create_virtual_display(config.display)
        input_injector = InputInjector(config.display)

        try:
            # A dropped connection (unplugged cable, killed app, or any other
            # disconnect WebRtcSession notices — see its
            # _on_connection_state_change) loops back to waiting for a new
            # one instead of tearing the whole session down: the virtual
            # display and input injector stay up, so reconnecting doesn't
            # mean restarting the session from the UI. Only an explicit
            # request_stop() exits this loop.
            while True:
                # A wired transport (Android over adb) streams video over its own
                # tunnel; everything else negotiates WebRTC.
                session_class = WiredSession if transport.supports_wired_stream else WebRtcSession
                session = session_class(display_server, input_injector, config.display)
                try:
                    self._report(State.WAITING, transport_name)
                    try:
                        await session.start(transport)
                    except ConnectionClosed as error:
                        # The device closed the signaling connection before
                        # the handshake finished — found live with the
                        # Android app: right after a dropped session the host
                        # reconnects through the tunnel, and if that lands
                        # on the app's about-to-be-recycled listener it gets
                        # `1001 going away`. That's "device not ready yet",
                        # the same as a disconnect, not a reason to kill the
                        # whole session (and the virtual display with it).
                        logger.warning("Device closed signaling mid-handshake (%s); waiting for it to reconnect.", error)
                        was_stop_requested = self._stop_requested.is_set()
                    else:
                        self._report(State.CONNECTED, transport_name)

                        closed = asyncio.ensure_future(session.wait_closed())
                        stopped = asyncio.ensure_future(self._stop_requested.wait())
                        waitables = {closed, stopped}

                        usb_gone_task = None
                        if isinstance(transport, UsbTransport):
                            usb_gone_task = asyncio.ensure_future(_wait_until_usb_unavailable())
                            waitables.add(usb_gone_task)

                        done, pending = await asyncio.wait(waitables, return_when=asyncio.FIRST_COMPLETED)
                        for task in pending:
                            task.cancel()
                        if pending:
                            await asyncio.gather(*pending, return_exceptions=True)
                        was_stop_requested = stopped in done
                finally:
                    # Closing here unconditionally is what makes the USB-gone
                    # watchdog above actually force a disconnect: wait_closed()
                    # itself might never have fired (media still flowing over
                    # Wi-Fi), but session.close() ends it regardless of why
                    # this block exited.
                    await session.close()

                await transport.disconnect()
                if was_stop_requested:
                    break

                self._report(State.WAITING, "device disconnected — waiting to reconnect")
                established = await self._establish_transport(config)
                if established is None:
                    # _establish_transport() already reported STOPPING/IDLE
                    # and tore down its (new, never-connected) transport;
                    # the outer finally below still tears down the display
                    # server/input injector this loop owns.
                    return
                transport, transport_name = established
        finally:
            self._report(State.STOPPING)
            input_injector.close()
            display_server.destroy_virtual_display()
            self._report(State.IDLE)

    def request_stop(self) -> None:
        self._stop_requested.set()
