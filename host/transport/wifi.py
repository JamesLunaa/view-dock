"""Wi-Fi transport: direct socket connection to the iPad over the LAN.

Handles discovery (so the iPad app can find the host without the user typing
an IP) and exposes a plain TCP/WebSocket endpoint that carries WebRTC
signaling (SDP offer/answer, ICE candidates).
"""

from host.transport.base import Transport


class WifiTransport(Transport):
    def __init__(self, port: int = 8765) -> None:
        self._port = port

    async def is_available(self) -> bool:
        # TODO: always True if the host has an active network interface;
        # actual reachability is determined once the iPad connects.
        raise NotImplementedError

    async def connect(self) -> None:
        # TODO: start a signaling server (e.g. websockets) on self._port,
        # optionally advertised via mDNS/Bonjour for iPad discovery.
        raise NotImplementedError

    async def disconnect(self) -> None:
        # TODO: stop the signaling server.
        raise NotImplementedError
