"""USB transport: tunnels a local TCP port to a matching port on the iPad via
`usbmuxd`, using the `iproxy` CLI from `libimobiledevice`.

`iproxy <local_port> <device_port>` makes the *host* listen on `local_port`
and relay each connection through USB to `device_port` **on the device** —
so the iPad app must be the one listening (a WebSocket server) on
`device_port`, and this class connects to it as a client through the tunnel,
the same way `websockets.connect()` would reach any other WebSocket server.

Requires `usbmuxd` running and `iproxy`/`idevice_id` on PATH (Arch package:
`libimobiledevice`).
"""

import asyncio
import json
import logging

import websockets
from websockets.asyncio.client import ClientConnection, connect

from host.transport.base import Transport

logger = logging.getLogger(__name__)


class UsbTransport(Transport):
    def __init__(self, local_port: int = 8766, device_port: int = 8766) -> None:
        self._local_port = local_port
        self._device_port = device_port
        self._iproxy_process: asyncio.subprocess.Process | None = None
        self._iproxy_log_task: asyncio.Task | None = None
        self._connection: ClientConnection | None = None

    async def is_available(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "idevice_id",
                "-l",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return False
        stdout, _ = await proc.communicate()
        return proc.returncode == 0 and bool(stdout.strip())

    async def connect(self) -> None:
        # iproxy's stdout/stderr must NOT be inherited: left to the default,
        # they go straight to this process's terminal, which is harmless for
        # the plain CLI (host/main.py) but corrupts a curses UI (host/ui/)
        # sharing that same terminal — its lines land mid-screen, fighting
        # curses for cursor control. Capture and route through logging
        # instead, same as every other component.
        self._iproxy_process = await asyncio.create_subprocess_exec(
            "iproxy", str(self._local_port), str(self._device_port),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._iproxy_log_task = asyncio.ensure_future(self._pump_iproxy_output())
        # Give iproxy a moment to bind its local listening socket before we
        # try to connect to it.
        self._connection = await self._connect_with_retry()

    async def disconnect(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
        if self._iproxy_process is not None:
            # iproxy exits on its own when the device goes away (unplugged
            # cable, USB enumeration drop) — terminate()ing a process that's
            # already gone raises ProcessLookupError, which otherwise took
            # down the whole reconnect flow right as it was trying to clean
            # up after a lost connection. wait() on an already-exited
            # process is safe (returns its exit code immediately).
            try:
                self._iproxy_process.terminate()
            except ProcessLookupError:
                pass
            await self._iproxy_process.wait()
            self._iproxy_process = None
        if self._iproxy_log_task is not None:
            self._iproxy_log_task.cancel()
            self._iproxy_log_task = None

    async def _pump_iproxy_output(self) -> None:
        assert self._iproxy_process is not None and self._iproxy_process.stdout is not None
        async for line in self._iproxy_process.stdout:
            logger.info("iproxy: %s", line.decode(errors="replace").rstrip())

    async def send_signal(self, message: dict) -> None:
        if self._connection is None:
            raise RuntimeError("Not connected.")
        await self._connection.send(json.dumps(message))

    async def receive_signal(self) -> dict:
        if self._connection is None:
            raise RuntimeError("Not connected.")
        raw = await self._connection.recv()
        return json.loads(raw)

    async def _connect_with_retry(
        self, fast_attempts: int = 20, fast_delay: float = 0.25, patient_delay: float = 1.0
    ) -> ClientConnection:
        """Retries indefinitely rather than giving up after `fast_attempts`.

        Found live: a device can be USB-paired (`idevice_id -l` sees it, so
        `UsbTransport.is_available()` returns True) well before the iPad app
        is actually open and listening — "connection refused" in that case
        just means "not ready yet," not a real failure, and the gap can be
        however long it takes a human to notice and tap the app icon, not
        the few seconds `iproxy` needs to bind its own socket this was
        originally tuned for. Giving up and raising after that short budget
        crashed the whole session. The caller (`HostRunner._establish_transport`)
        already races this against a stop request, so cancellation —  not an
        internal attempt cap — is how this is meant to end.
        """
        attempt = 0
        while True:
            try:
                # ping_interval=None: `websockets` otherwise auto-sends a
                # ping control frame after 20s of idle connection. The iPad's
                # WebSocketServer.swift is a minimal hand-rolled RFC 6455
                # server that only parses text frames in receiveText() — a
                # ping (or anything else non-text) makes it throw
                # ServerError.unexpectedFrame ("error 3") and the connection
                # dies before a signaling message is ever exchanged. Only
                # bites when there's a 20s+ gap between connecting and the
                # first send_signal() (e.g. slow ICE gathering, or a human
                # pausing mid-debug) — ordinary fast sessions never hit it.
                return await connect(f"ws://127.0.0.1:{self._local_port}", ping_interval=None)
            except (ConnectionRefusedError, OSError, websockets.exceptions.WebSocketException):
                attempt += 1
                # Fast retries cover the "iproxy just needs a moment to bind"
                # case without adding latency to an already-ready connect;
                # past that, slow down rather than spamming "connection
                # refused" once a second while patiently waiting for a human.
                await asyncio.sleep(fast_delay if attempt <= fast_attempts else patient_delay)
