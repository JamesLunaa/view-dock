"""Entrypoint for the view-dock host server.

Picks a transport (USB preferred, Wi-Fi fallback per CLAUDE.md), brings up
the virtual display, and runs the WebRTC session. Run from the repo root:

    python -m host.main
"""

import asyncio

from host.config import HostConfig
from host.displayserver import X11DisplayServer
from host.input.injector import InputInjector
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
    input_injector = InputInjector(config.display)

    session = WebRtcSession(display_server, input_injector, config.display)
    try:
        await session.start(transport)
        await session.wait_closed()
    finally:
        await session.close()
        input_injector.close()
        display_server.destroy_virtual_display()
        await transport.disconnect()


if __name__ == "__main__":
    asyncio.run(run())
