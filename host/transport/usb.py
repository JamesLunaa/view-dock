"""USB transport: tunnels a local TCP port to a matching port on the iPad via
`usbmuxd`, using the `iproxy` CLI from `libimobiledevice`. Once the tunnel is
up, the same WebSocket-based signaling used by WifiTransport runs over it —
only the socket setup differs.

Requires `usbmuxd` running and `iproxy`/`idevice_id` on PATH (Arch package:
`libimobiledevice`).
"""

import asyncio

from host.transport.base import Transport
from host.transport.wifi import WifiTransport


class UsbTransport(Transport):
    def __init__(self, local_port: int = 8766, device_port: int = 8766) -> None:
        self._local_port = local_port
        self._device_port = device_port
        self._iproxy_process: asyncio.subprocess.Process | None = None
        self._tunnel = WifiTransport(port=local_port)

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
        self._iproxy_process = await asyncio.create_subprocess_exec(
            "iproxy", str(self._local_port), str(self._device_port),
        )
        await self._tunnel.connect()

    async def disconnect(self) -> None:
        await self._tunnel.disconnect()
        if self._iproxy_process is not None:
            self._iproxy_process.terminate()
            await self._iproxy_process.wait()
            self._iproxy_process = None

    async def send_signal(self, message: dict) -> None:
        await self._tunnel.send_signal(message)

    async def receive_signal(self) -> dict:
        return await self._tunnel.receive_signal()
