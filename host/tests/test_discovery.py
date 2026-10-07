# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""mDNS advertising with `zeroconf` mocked: what is registered, that it is
unregistered on stop, and that any failure is swallowed (discovery is optional)."""

import asyncio
import socket
from unittest.mock import AsyncMock, MagicMock, patch

from host.transport import discovery
from host.transport.discovery import SERVICE_TYPE, ServiceAdvertiser
from protocol import messages


def _run(coro):
    return asyncio.run(coro)


def test_registers_viewdock_service_on_lan_addresses_with_protocol_version():
    zc = MagicMock()
    zc.async_register_service = AsyncMock()
    zc.async_unregister_service = AsyncMock()
    zc.async_close = AsyncMock()

    async def body():
        advertiser = ServiceAdvertiser(8765, name="arch-box")
        with (
            patch.object(discovery.netinfo, "lan_addresses", return_value=["192.168.1.20"]),
            patch("zeroconf.asyncio.AsyncZeroconf", return_value=zc) as factory,
        ):
            await advertiser.start()
            assert factory.call_args.kwargs["interfaces"] == ["192.168.1.20"]
        info = zc.async_register_service.call_args.args[0]
        assert info.type == SERVICE_TYPE == "_viewdock._tcp.local."
        assert info.name == f"arch-box.{SERVICE_TYPE}"
        assert info.port == 8765
        assert info.addresses == [socket.inet_aton("192.168.1.20")]
        assert info.properties == {
            b"protocol_version": messages.PROTOCOL_VERSION.encode(),
            b"name": b"arch-box",
        }
        await advertiser.stop()
        zc.async_unregister_service.assert_awaited_once_with(info)
        zc.async_close.assert_awaited_once()

    _run(body())


def test_failure_to_start_is_swallowed():
    async def body():
        advertiser = ServiceAdvertiser(8765, name="x")
        with (
            patch.object(discovery.netinfo, "lan_addresses", return_value=["192.168.1.20"]),
            patch("zeroconf.asyncio.AsyncZeroconf", side_effect=OSError("no multicast")),
        ):
            await advertiser.start()  # must not raise
        await advertiser.stop()  # nothing to stop; must not raise

    _run(body())


def test_not_on_a_network_advertises_nothing():
    async def body():
        advertiser = ServiceAdvertiser(8765, name="x")
        with (
            patch.object(discovery.netinfo, "lan_addresses", return_value=[]),
            patch("zeroconf.asyncio.AsyncZeroconf") as factory,
        ):
            await advertiser.start()
            factory.assert_not_called()

    _run(body())
