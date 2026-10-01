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

from host.config import DisplayConfig, HostConfig
from host.displayserver import (
    DisplayServer,
    PassthroughDisplayServer,
    TestPatternDisplayServer,
    X11DisplayServer,
)
from host.input.injector import InputInjector
from host.streaming import WebRtcSession
from host.transport import UsbTransport, WifiTransport

logger = logging.getLogger(__name__)


class State(enum.Enum):
    IDLE = "idle"
    STARTING = "starting"
    WAITING = "waiting for iPad"
    CONNECTED = "connected"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class StatusEvent:
    state: State
    detail: str = ""


async def choose_transport(config: HostConfig):
    usb = UsbTransport()
    if config.prefer_usb and await usb.is_available():
        return usb
    return WifiTransport()


async def _wait_until_usb_available(poll_interval: float = 1.0) -> None:
    """Polls until a USB-attached iPad shows up. Used to let a session that
    fell back to Wi-Fi (no device plugged in yet when it started) switch to
    USB the moment a cable appears, instead of only checking once at
    startup and then ignoring USB for the rest of the session."""
    usb = UsbTransport()
    while not await usb.is_available():
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
                transport = UsbTransport()
                transport_name = type(transport).__name__
                continue

            connect_task.result()
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

        session = WebRtcSession(display_server, input_injector, config.display)
        try:
            self._report(State.WAITING, transport_name)
            await session.start(transport)
            self._report(State.CONNECTED, transport_name)

            closed = asyncio.ensure_future(session.wait_closed())
            stopped = asyncio.ensure_future(self._stop_requested.wait())
            await asyncio.wait({closed, stopped}, return_when=asyncio.FIRST_COMPLETED)
            for pending in (closed, stopped):
                if not pending.done():
                    pending.cancel()
        finally:
            self._report(State.STOPPING)
            await session.close()
            input_injector.close()
            display_server.destroy_virtual_display()
            await transport.disconnect()
            self._report(State.IDLE)

    def request_stop(self) -> None:
        self._stop_requested.set()
