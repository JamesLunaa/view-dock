# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Wi-Fi discovery: advertise the host over mDNS / DNS-SD ("Bonjour") so the
apps can list it instead of making the user type an IP address.

Service type `_viewdock._tcp`, on the Wi-Fi listener's port. The TXT record
carries `protocol_version` (so an app can refuse an incompatible host before
connecting) and `name`. Discovery is a convenience, never a dependency: any
failure here is logged and swallowed, and a typed IP keeps working.
"""

import asyncio
import logging
import socket

from host import netinfo
from protocol import messages

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_viewdock._tcp.local."


def txt_properties(name: str) -> dict[str, str]:
    return {"protocol_version": messages.PROTOCOL_VERSION, "name": name}


class ServiceAdvertiser:
    def __init__(self, port: int, name: str | None = None) -> None:
        self._port = port
        self._name = name or socket.gethostname().split(".")[0] or "view-dock"
        self._zeroconf = None
        self._info = None

    async def start(self) -> None:
        """Begin advertising. Never raises."""
        try:
            await self._start()
        except Exception as exc:
            logger.warning("Wi-Fi discovery is unavailable (%s); clients must type the host's IP.", exc)
            await self.stop()

    async def _start(self) -> None:
        from zeroconf import IPVersion, ServiceInfo
        from zeroconf.asyncio import AsyncZeroconf

        # Only the LAN addresses (netinfo skips virbr0/docker/tailscale/loopback),
        # so a phone is never told an address it cannot reach.
        addresses = await asyncio.to_thread(netinfo.lan_addresses)
        if not addresses:
            logger.warning("Wi-Fi discovery skipped: this machine is not on a network.")
            return
        self._info = ServiceInfo(
            SERVICE_TYPE,
            f"{self._name}.{SERVICE_TYPE}",
            port=self._port,
            addresses=[socket.inet_aton(address) for address in addresses],
            properties=txt_properties(self._name),
        )
        self._zeroconf = AsyncZeroconf(interfaces=addresses, ip_version=IPVersion.V4Only)
        await self._zeroconf.async_register_service(self._info, allow_name_change=True)
        logger.info("Advertising %s on port %d (%s)", self._info.name, self._port, ", ".join(addresses))

    async def stop(self) -> None:
        zeroconf, info = self._zeroconf, self._info
        self._zeroconf = self._info = None
        if zeroconf is None:
            return
        try:
            if info is not None:
                await zeroconf.async_unregister_service(info)
            await zeroconf.async_close()
        except Exception:
            logger.warning("Stopping Wi-Fi discovery failed; ignoring.", exc_info=True)
