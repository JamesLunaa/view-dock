# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Wi-Fi transport: direct socket connections from clients over the LAN.

`WifiListener` runs one WebSocket server that clients connect to; every
connection it accepts becomes its own `WifiConnection`, a `Transport` the
session code uses for WebRTC signaling (SDP offer/answer exchange) exactly as
it would any other. Any number of clients can be connected at once — whether
to admit another is the caller's decision (see `HostRunner`), not the
listener's. Discovery is a separate concern: mDNS advertising layers on top of
the listener without changing it.
"""

import asyncio
import json

import websockets
from websockets.asyncio.server import ServerConnection, serve

from host.transport.base import Transport


class WifiConnection(Transport):
    """One accepted client connection."""

    def __init__(self, websocket: ServerConnection) -> None:
        self._websocket = websocket

    @property
    def label(self) -> str:
        remote = self._websocket.remote_address
        return f"Wi-Fi {remote[0]}" if remote else "Wi-Fi"

    async def is_available(self) -> bool:
        return not self.closed

    @property
    def closed(self) -> bool:
        return self._websocket.close_code is not None

    async def connect(self) -> None:
        """Already connected: the client dialed in."""

    async def disconnect(self) -> None:
        await self._websocket.close()

    async def send_signal(self, message: dict) -> None:
        await self._websocket.send(json.dumps(message))

    async def receive_signal(self) -> dict:
        return json.loads(await self._websocket.recv())


class WifiListener:
    def __init__(self, port: int = 8765) -> None:
        self._port = port
        self._server: websockets.asyncio.server.Server | None = None
        self._accepted: asyncio.Queue[WifiConnection] = asyncio.Queue()

    async def start(self) -> None:
        self._server = await serve(self._on_connect, "0.0.0.0", self._port)

    async def accept(self) -> WifiConnection:
        """Block until the next client connects."""
        return await self._accepted.get()

    async def stop(self) -> None:
        if self._server is None:
            return
        # close() also closes every open client connection.
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _on_connect(self, websocket: ServerConnection) -> None:
        self._accepted.put_nowait(WifiConnection(websocket))
        # The connection closes when this handler returns, so stay alive for
        # its lifetime while the session uses it from elsewhere.
        await websocket.wait_closed()
