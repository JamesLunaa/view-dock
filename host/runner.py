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

    async def run(self) -> None:
        config = HostConfig(display=self._display_config)

        cleaned = X11DisplayServer.cleanup_stale_virtual_outputs()
        if cleaned:
            self._report(State.STARTING, f"cleared stale output(s): {', '.join(cleaned)}")

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
        self._report(State.WAITING, f"connecting via {transport_name}")
        connect_task = asyncio.ensure_future(transport.connect())
        stop_task = asyncio.ensure_future(self._stop_requested.wait())
        done, pending = await asyncio.wait({connect_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if connect_task not in done:
            self._report(State.STOPPING)
            await transport.disconnect()
            self._report(State.IDLE)
            return
        connect_task.result()

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
