"""Covers the bug hit live in host/ui/: pressing stop while HostRunner.run()
is still blocked inside transport.connect() (e.g. Wi-Fi waiting for an iPad
to show up) did nothing, because nothing was awaiting the stop-request event
yet. request_stop() must be effective at that point too, not just once a
session is already established.
"""

import asyncio
from unittest.mock import patch

from host.runner import HostRunner, State
from host.transport.base import Transport


class HangingTransport(Transport):
    """Never resolves connect() on its own — the shape of WifiTransport
    waiting for an iPad that hasn't shown up yet."""

    def __init__(self) -> None:
        self.disconnected = False

    async def is_available(self) -> bool:
        return True

    async def connect(self) -> None:
        await asyncio.Event().wait()  # blocks forever unless cancelled

    async def disconnect(self) -> None:
        self.disconnected = True

    async def send_signal(self, message: dict) -> None:
        raise NotImplementedError

    async def receive_signal(self) -> dict:
        raise NotImplementedError


def test_request_stop_during_connect_returns_to_idle():
    async def body():
        transport = HangingTransport()
        states: list[State] = []

        runner = HostRunner(display_config=None, on_status=lambda e: states.append(e.state))

        async def fake_choose_transport(_config):
            return transport

        with (
            patch("host.runner.X11DisplayServer.cleanup_stale_virtual_outputs", return_value=[]),
            patch("host.runner.choose_transport", side_effect=fake_choose_transport),
        ):
            run_task = asyncio.ensure_future(runner.run())
            await asyncio.sleep(0.05)  # let it reach the blocked connect()
            runner.request_stop()
            await asyncio.wait_for(run_task, timeout=1)

        assert transport.disconnected
        assert states[-1] is State.IDLE
        assert State.STOPPING in states

    asyncio.run(body())
