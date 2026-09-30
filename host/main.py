"""Entrypoint for the view-dock host server.

Picks a transport (USB preferred, Wi-Fi fallback per CLAUDE.md), brings up
the virtual display, and runs the WebRTC session. Run from the repo root:

    python -m host.main
"""

import asyncio

from host.config import HostConfig
from host.displayserver import X11DisplayServer
from host.streaming import WebRtcSession
from host.transport import UsbTransport, WifiTransport


async def choose_transport(config: HostConfig):
    usb = UsbTransport()
    if config.prefer_usb and await usb.is_available():
        return usb
    return WifiTransport()


async def run() -> None:
    config = HostConfig.default()
    transport = await choose_transport(config)
    await transport.connect()

    display_server = X11DisplayServer()
    display_server.create_virtual_display(config.display)

    session = WebRtcSession(display_server)
    try:
        await session.start()
        # TODO: block here until the session ends (e.g. `bye` message or
        # transport disconnect), instead of returning immediately.
    finally:
        await session.close()
        display_server.destroy_virtual_display()
        await transport.disconnect()


if __name__ == "__main__":
    asyncio.run(run())
