# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Covers a crash hit live: unplugging the iPad kills `iproxy` on its own
(it exits once the USB device it's tunneling to disappears), and
UsbTransport.disconnect() calling .terminate() on that already-dead process
raised ProcessLookupError — uncaught, this took down the whole reconnect
flow right as it was trying to clean up after a lost connection.
"""

import asyncio
from unittest.mock import patch

import pytest

from host.transport.usb import UsbTransport


class FakeAlreadyExitedProcess:
    """Stands in for asyncio.subprocess.Process after its process has
    already exited on its own — terminate() on a real one in that state
    raises ProcessLookupError."""

    def __init__(self) -> None:
        self.wait_called = False

    def terminate(self) -> None:
        raise ProcessLookupError

    async def wait(self) -> int:
        self.wait_called = True
        return 0


def test_disconnect_tolerates_iproxy_already_exited():
    async def body():
        transport = UsbTransport()
        process = FakeAlreadyExitedProcess()
        transport._iproxy_process = process

        await transport.disconnect()  # must not raise

        assert process.wait_called
        assert transport._iproxy_process is None

    asyncio.run(body())


def test_connect_with_retry_keeps_retrying_past_the_old_attempt_cap():
    """Covers a crash hit live: plugging in the iPad without opening the app
    yet is USB-paired (idevice_id sees it) well before anything listens on
    the tunneled port, so every attempt gets "connection refused" — this
    used to give up and raise after a short fixed budget, crashing the whole
    host session. It must now keep retrying indefinitely, relying on the
    caller to cancel it instead of an internal cap."""

    async def body():
        transport = UsbTransport()
        attempts = 0

        async def always_refused(*_args, **_kwargs):
            nonlocal attempts
            attempts += 1
            raise ConnectionRefusedError

        with patch("host.transport.usb.connect", side_effect=always_refused):
            task = asyncio.ensure_future(
                transport._connect_with_retry(fast_attempts=3, fast_delay=0.001, patient_delay=0.001)
            )
            # Old behavior raised after `fast_attempts` (here: 3) tries —
            # waiting long enough for well more than that to elapse and
            # confirming it's still going (not raised, not finished) proves
            # the cap no longer ends the retry loop on its own.
            await asyncio.sleep(0.05)
            assert not task.done()
            assert attempts > 3

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(body())
