"""Wi-Fi transport: direct socket connection to the iPad over the LAN.

Runs a WebSocket server that the iPad connects to for WebRTC signaling (SDP
offer/answer exchange). Discovery is out of scope for this phase — the iPad
app is pointed at the host's IP directly; mDNS/Bonjour advertising can be
layered on later without changing this class's interface.
"""

import asyncio
import json

import websockets
from websockets.asyncio.server import ServerConnection, serve

from host.transport.base import Transport


class WifiTransport(Transport):
    def __init__(self, port: int = 8765) -> None:
        self._port = port
        self._server: websockets.asyncio.server.Server | None = None
        self._connection: ServerConnection | None = None
        self._connected = asyncio.Event()

    async def is_available(self) -> bool:
        # Wi-Fi is always a candidate; actual reachability is only known once
        # an iPad connects to the signaling server in connect().
        return True

    async def connect(self) -> None:
        self._server = await serve(self._on_connect, "0.0.0.0", self._port)
        await self._connected.wait()

    async def disconnect(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._connected.clear()

    async def send_signal(self, message: dict) -> None:
        if self._connection is None:
            raise RuntimeError("No iPad connected.")
        await self._connection.send(json.dumps(message))

    async def receive_signal(self) -> dict:
        if self._connection is None:
            raise RuntimeError("No iPad connected.")
        raw = await self._connection.recv()
        return json.loads(raw)

    async def _on_connect(self, websocket: ServerConnection) -> None:
        # Single iPad client at a time; first connection wins. Stay alive for
        # the connection's lifetime so send_signal/receive_signal can use it
        # from elsewhere in the session while this handler just holds it open.
        self._connection = websocket
        self._connected.set()
        await websocket.wait_closed()
