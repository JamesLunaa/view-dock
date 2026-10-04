# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Covers how the host tells a wired-capable iPad app from an older WebRTC-only
one: over `iproxy` nothing identifies the build, so a new app sends `hello`
the moment the tunnel connects and an old one stays silent. Uses a real local
WebSocket server standing in for the app (the iPad is the server over USB).
"""

import asyncio
import json

import pytest
import websockets
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from host.transport import usb
from host.transport.adb import AdbTransport
from host.transport.usb import UsbTransport, is_wired_hello

HELLO_12 = json.dumps({"type": "hello", "role": "ipad", "protocol_version": "1.2"})


@pytest.mark.parametrize(
    "raw, expected",
    [
        (HELLO_12, True),
        (json.dumps({"type": "hello", "role": "ipad", "protocol_version": "1.10"}), True),
        (json.dumps({"type": "hello", "role": "ipad", "protocol_version": "2.0"}), True),
        (json.dumps({"type": "hello", "role": "ipad", "protocol_version": "1.1"}), False),  # predates the wired stream
        (json.dumps({"type": "offer", "sdp": "x"}), False),
        (json.dumps({"type": "hello", "role": "ipad"}), False),  # no version
        ("not json", False),
        (b"\x01\x02", False),
    ],
)
def test_wired_hello_detection(raw, expected):
    assert is_wired_hello(raw) is expected


async def _probe_against(handler, timeout=0.3) -> UsbTransport:
    """Runs the real probe against a server running `handler`."""
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        transport = UsbTransport()
        transport._connection = await connect(f"ws://127.0.0.1:{port}", compression=None)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(usb, "_CLIENT_HELLO_TIMEOUT_S", timeout)
            await transport._probe_for_wired_client()
        await transport._connection.close()
        return transport


def test_app_that_announces_itself_gets_the_wired_stream():
    async def body():
        async def new_app(ws):
            await ws.send(HELLO_12)
            await asyncio.sleep(0.5)

        transport = await _probe_against(new_app)
        assert transport.supports_wired_stream is True

    asyncio.run(body())


def test_silent_old_app_falls_back_to_webrtc():
    async def body():
        async def old_app(ws):
            await asyncio.sleep(1)  # waits for our offer, says nothing

        transport = await _probe_against(old_app)
        assert transport.supports_wired_stream is False

    asyncio.run(body())


def test_unexpected_first_message_is_kept_not_lost():
    async def body():
        async def odd_app(ws):
            await ws.send(json.dumps({"type": "offer", "sdp": "stray"}))
            await asyncio.sleep(0.5)

        transport = await _probe_against(odd_app)
        assert transport.supports_wired_stream is False
        # Still readable afterwards, in order, by the normal signaling path.
        assert transport._pending and json.loads(transport._pending[0])["sdp"] == "stray"

    asyncio.run(body())


def test_adb_transport_never_probes():
    """The Android app is always wired over USB and sends no hello, so probing
    would only add a pointless delay."""
    assert AdbTransport.supports_wired_stream is True
    assert UsbTransport.supports_wired_stream is False
