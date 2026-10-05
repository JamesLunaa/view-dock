# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Entrypoint for the view-dock host server.

Picks a transport (USB preferred, Wi-Fi fallback), brings up
the virtual display, and runs the WebRTC session. Run from the repo root:

    python -m host.main

Set VIEWDOCK_PASSTHROUGH_DISPLAY=1 to capture the real primary monitor
instead of creating a virtual one via xrandr — useful on a machine without a
`xf86-video-dummy`-configured Xorg session (e.g. plain Wayland/Xwayland, see
host/displayserver/passthrough.py). Note that on Wayland, passthrough still
won't see real desktop content (Xwayland doesn't expose it) — for that case,
set VIEWDOCK_TEST_PATTERN_DISPLAY=1 instead to validate the rest of the
pipeline against a synthetic animated frame (host/displayserver/test_pattern.py).

For a terminal UI instead of this raw log stream (status at a glance, a
device-resolution picker, start/stop without re-typing the command), see
`python -m host.ui`.
"""

import asyncio
import logging
import os
import signal

from host.config import HostConfig
from host.runner import HostRunner, StatusEvent

logger = logging.getLogger(__name__)


def _log_status(event: StatusEvent) -> None:
    logger.info("status: %s%s", event.state.value, f" ({event.detail})" if event.detail else "")


async def run() -> None:
    config = HostConfig.default()
    runner = HostRunner(config.display, on_status=_log_status)

    # SIGINT is left to asyncio's default (raises KeyboardInterrupt, caught
    # by asyncio.run() below) so Ctrl+C still cancels immediately even mid
    # connect. SIGTERM has no such default in asyncio, so a plain `kill` used
    # to skip the `finally` cleanup entirely, leaving a stale xrandr mode
    # behind — cancelling the running task here routes it through the same
    # cleanup path instead.
    main_task = asyncio.current_task()
    assert main_task is not None
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, main_task.cancel)

    try:
        await runner.run()
    except asyncio.CancelledError:
        pass


def main() -> None:
    # Several components degrade gracefully rather than failing hard (cursor
    # overlay, screen-layout tracking, schema-invalid control messages) and
    # say so only via logging — without a handler configured those notices
    # would be silently dropped. VIEWDOCK_LOG_LEVEL=DEBUG for more.
    logging.basicConfig(
        level=os.environ.get("VIEWDOCK_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
