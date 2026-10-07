# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""The Wi-Fi listener over real localhost sockets: several clients connected
at once, each a separate `WifiConnection` that signals independently."""

import asyncio
import json

from websockets.asyncio.client import connect

from host.transport.usb import free_local_port
from host.transport.wifi import WifiListener


def test_accepts_several_clients_at_once_each_with_its_own_connection():
    async def body():
        port = free_local_port()
        listener = WifiListener(port=port)
        await listener.start()
        try:
            async with connect(f"ws://127.0.0.1:{port}") as a, connect(f"ws://127.0.0.1:{port}") as b:
                first = await asyncio.wait_for(listener.accept(), timeout=1)
                second = await asyncio.wait_for(listener.accept(), timeout=1)
                assert first is not second

                await first.send_signal({"n": 1})
                await second.send_signal({"n": 2})
                assert json.loads(await a.recv()) == {"n": 1}
                assert json.loads(await b.recv()) == {"n": 2}

                await a.send(json.dumps({"from": "a"}))
                assert await first.receive_signal() == {"from": "a"}

                await first.disconnect()
                assert first.closed and not second.closed
        finally:
            await listener.stop()

    asyncio.run(body())
