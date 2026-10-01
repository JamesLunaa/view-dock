"""Covers the bug hit live in host/ui/: pressing stop while HostRunner.run()
is still blocked inside transport.connect() (e.g. Wi-Fi waiting for an iPad
to show up) did nothing, because nothing was awaiting the stop-request event
yet. request_stop() must be effective at that point too, not just once a
session is already established.
"""

import asyncio
from unittest.mock import patch

from host.config import HostConfig
from host.runner import HostRunner, State
from host.transport.base import Transport
from host.transport.wifi import WifiTransport


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


class FakeUsbTransport(Transport):
    """Connects instantly — stands in for a real UsbTransport once a cable
    is plugged in, without shelling out to iproxy/idevice_id."""

    instances: list["FakeUsbTransport"] = []

    def __init__(self) -> None:
        self.connected = False
        self.disconnected = False
        FakeUsbTransport.instances.append(self)

    async def is_available(self) -> bool:
        return True

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def send_signal(self, message: dict) -> None:
        raise NotImplementedError

    async def receive_signal(self) -> dict:
        raise NotImplementedError


def test_switches_from_wifi_to_usb_when_cable_appears_mid_wait():
    """Covers the bug reported live: starting with no iPad plugged in falls
    back to Wi-Fi, and plugging in USB afterward did nothing until the whole
    session was restarted — _wait_until_usb_available() should catch this
    instead of choose_transport() only ever being consulted once."""

    async def body():
        FakeUsbTransport.instances.clear()
        wifi = WifiTransport()
        states: list[tuple[State, str]] = []

        runner = HostRunner(
            display_config=None,
            on_status=lambda e: states.append((e.state, e.detail)),
        )

        async def fake_choose_transport(_config):
            return wifi

        async def hang_forever(*_args, **_kwargs):
            await asyncio.Event().wait()

        async def usb_already_available(*_args, **_kwargs):
            return None

        with (
            patch.object(WifiTransport, "connect", side_effect=hang_forever, autospec=True),
            patch.object(WifiTransport, "disconnect", autospec=True),
            patch("host.runner.choose_transport", side_effect=fake_choose_transport),
            patch("host.runner._wait_until_usb_available", side_effect=usb_already_available),
            patch("host.runner.UsbTransport", FakeUsbTransport),
        ):
            config = HostConfig(display=None)
            result = await asyncio.wait_for(runner._establish_transport(config), timeout=1)

        assert result is not None
        transport, transport_name = result
        assert isinstance(transport, FakeUsbTransport)
        assert transport_name == "FakeUsbTransport"
        assert transport.connected
        assert any(state is State.STARTING and "switching from Wi-Fi" in detail for state, detail in states)

    asyncio.run(body())
