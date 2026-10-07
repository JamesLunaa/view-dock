# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

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
import socket

import websockets
from websockets.asyncio.client import ClientConnection, connect

from host.transport.base import Transport
from protocol import messages

logger = logging.getLogger(__name__)


# How long to wait, after the tunnel connects, for the app to announce itself
# before assuming it is an older WebRTC-only build. Apps that support the wired
# stream send `hello` immediately, so this only ever delays an old build.
_CLIENT_HELLO_TIMEOUT_S = 1.0


def free_local_port() -> int:
    """A currently unused local TCP port, for one device's tunnel — several
    devices can be plugged in at once and each needs its own."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def is_wired_hello(raw: str | bytes) -> bool:
    """True for a `hello` whose protocol_version is new enough for the wired stream."""
    if not isinstance(raw, str):
        return False
    try:
        message = json.loads(raw)
        major, minor = (int(part) for part in str(message["protocol_version"]).split("."))
        return message["type"] == messages.TYPE_HELLO and (major, minor) >= messages.WIRED_STREAM_MIN_VERSION
    except (ValueError, KeyError, TypeError):
        return False


class UsbTransport(Transport):
    def __init__(self, local_port: int = 8766, device_port: int = 8766, serial: str | None = None) -> None:
        self._local_port = local_port
        self._device_port = device_port
        # Which device this tunnel is for. None = whichever the tool picks, which is
        # only right while a single device is attached.
        self.serial = serial
        self._iproxy_process: asyncio.subprocess.Process | None = None
        self._iproxy_log_task: asyncio.Task | None = None
        self._connection: ClientConnection | None = None
        # A message read while probing that turned out not to be a wired hello.
        self._pending: list[str | bytes] = []

    @property
    def label(self) -> str:
        return f"USB {self.serial[:8]}" if self.serial else "USB"

    def _tunnel_argv(self) -> list[str]:
        argv = ["iproxy"]
        if self.serial:
            argv += ["-u", self.serial]
        return [*argv, str(self._local_port), str(self._device_port)]

    @classmethod
    async def list_devices(cls) -> list[str]:
        """Identifiers (UDIDs) of the attached devices, `[]` when the tool is missing."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "idevice_id",
                "-l",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return []
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return []
        return stdout.decode(errors="replace").split()

    async def is_available(self) -> bool:
        return bool(await self.list_devices())

    async def connect(self) -> None:
        # iproxy's stdout/stderr must NOT be inherited: left to the default,
        # they go straight to this process's terminal, which is harmless for
        # the plain CLI (host/main.py) but corrupts a curses UI (host/ui/)
        # sharing that same terminal — its lines land mid-screen, fighting
        # curses for cursor control. Capture and route through logging
        # instead, same as every other component.
        self._iproxy_process = await asyncio.create_subprocess_exec(
            *self._tunnel_argv(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._iproxy_log_task = asyncio.ensure_future(self._pump_iproxy_output())
        # Give iproxy a moment to bind its local listening socket before we
        # try to connect to it.
        self._connection = await self._connect_with_retry()
        self._pending = []
        self.__dict__.pop("supports_wired_stream", None)  # re-decided per connection
        if not self.supports_wired_stream:
            await self._probe_for_wired_client()

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

    async def _probe_for_wired_client(self) -> None:
        """Decides between the wired stream and WebRTC for this connection.

        Over `iproxy` the host can't tell which build of the iPad app is
        listening, so a build that understands the wired stream sends `hello`
        the moment the tunnel connects. Silence means an older, WebRTC-only
        build, which is waiting for our SDP offer — so after a short wait the
        normal flow proceeds. (`AdbTransport` skips this: the Android app is
        always wired over USB.)
        """
        assert self._connection is not None
        try:
            raw = await asyncio.wait_for(self._connection.recv(), timeout=_CLIENT_HELLO_TIMEOUT_S)
        except asyncio.TimeoutError:
            return
        if is_wired_hello(raw):
            self.supports_wired_stream = True
            logger.info("Client announced wired-stream support")
        else:
            self._pending.append(raw)

    async def send_message(self, data: str | bytes) -> None:
        """Send one raw WebSocket message (text or binary) — used by the wired
        stream, where this connection carries the whole session."""
        if self._connection is None:
            raise RuntimeError("Not connected.")
        await self._connection.send(data)

    async def receive_message(self) -> str | bytes:
        if self._connection is None:
            raise RuntimeError("Not connected.")
        if self._pending:
            return self._pending.pop(0)
        return await self._connection.recv()

    async def send_signal(self, message: dict) -> None:
        if self._connection is None:
            raise RuntimeError("Not connected.")
        await self._connection.send(json.dumps(message))

    async def receive_signal(self) -> dict:
        if self._connection is None:
            raise RuntimeError("Not connected.")
        raw = self._pending.pop(0) if self._pending else await self._connection.recv()
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
                return await connect(
                    f"ws://127.0.0.1:{self._local_port}",
                    ping_interval=None,
                    # Video frames are already compressed; deflating them just burns CPU.
                    compression=None,
                )
            except (ConnectionRefusedError, OSError, websockets.exceptions.WebSocketException):
                attempt += 1
                # Fast retries cover the "iproxy just needs a moment to bind"
                # case without adding latency to an already-ready connect;
                # past that, slow down rather than spamming "connection
                # refused" once a second while patiently waiting for a human.
                await asyncio.sleep(fast_delay if attempt <= fast_attempts else patient_delay)
