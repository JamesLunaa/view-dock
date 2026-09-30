"""USB transport: tunnels a local TCP port to a matching port on the iPad via
`usbmuxd`, using the `iproxy` CLI from `libimobiledevice`. Once the tunnel is
up, the same WebRTC signaling protocol used by WifiTransport runs over it —
only the socket setup differs.

Requires `usbmuxd` running and `iproxy` on PATH (Arch package:
`libimobiledevice`).
"""

import asyncio

from host.transport.base import Transport


class UsbTransport(Transport):
    def __init__(self, local_port: int = 8766, device_port: int = 8766) -> None:
        self._local_port = local_port
        self._device_port = device_port
        self._iproxy_process: asyncio.subprocess.Process | None = None

    async def is_available(self) -> bool:
        # TODO: check `usbmuxd` for an attached device (e.g. via
        # `idevice_id -l` from libimobiledevice).
        raise NotImplementedError

    async def connect(self) -> None:
        # TODO: spawn `iproxy <local_port> <device_port>` as a subprocess,
        # then treat localhost:<local_port> like WifiTransport's socket.
        raise NotImplementedError

    async def disconnect(self) -> None:
        # TODO: terminate self._iproxy_process if running.
        raise NotImplementedError
