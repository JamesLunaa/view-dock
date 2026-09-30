"""Entrypoint for the view-dock host server.

Picks a transport (USB preferred, Wi-Fi fallback per CLAUDE.md), brings up
the virtual display, and runs the WebRTC session. Run from the repo root:

    python -m host.main

Set VIEWDOCK_PASSTHROUGH_DISPLAY=1 to capture the real primary monitor
instead of creating a virtual one via xrandr — useful on a machine without a
`xf86-video-dummy`-configured Xorg session (e.g. plain Wayland/Xwayland, see
host/displayserver/passthrough.py). Note that on Wayland, passthrough still
won't see real desktop content (Xwayland doesn't expose it) — for that case,
set VIEWDOCK_TEST_PATTERN_DISPLAY=1 instead to validate the rest of the
pipeline against a synthetic animated frame (host/displayserver/test_pattern.py).
"""

import asyncio
import logging
import os

from host.config import HostConfig
from host.displayserver import (
    DisplayServer,
    PassthroughDisplayServer,
    TestPatternDisplayServer,
    X11DisplayServer,
)
from host.input.injector import InputInjector
from host.streaming import WebRtcSession
from host.transport import UsbTransport, WifiTransport


async def choose_transport(config: HostConfig):
    usb = UsbTransport()
    if config.prefer_usb and await usb.is_available():
        return usb
    return WifiTransport()


def choose_display_server() -> DisplayServer:
    if os.environ.get("VIEWDOCK_TEST_PATTERN_DISPLAY"):
        return TestPatternDisplayServer()
    if os.environ.get("VIEWDOCK_PASSTHROUGH_DISPLAY"):
        return PassthroughDisplayServer()
    return X11DisplayServer()


async def run() -> None:
    config = HostConfig.default()
    transport = await choose_transport(config)
    await transport.connect()

    display_server = choose_display_server()
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
    # Several components degrade gracefully rather than failing hard (cursor
    # overlay, screen-layout tracking, schema-invalid control messages) and
    # say so only via logging — without a handler configured those notices
    # would be silently dropped. VIEWDOCK_LOG_LEVEL=DEBUG for more.
    logging.basicConfig(
        level=os.environ.get("VIEWDOCK_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    asyncio.run(run())
