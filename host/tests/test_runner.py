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


class FakeDisplayServerForRunner:
    """Tracks create/destroy calls so the test can assert the virtual
    display is brought up exactly once and torn down exactly once — not
    recreated on every reconnect."""

    def __init__(self) -> None:
        self.created = 0
        self.destroyed = 0

    def create_virtual_display(self, config) -> None:
        self.created += 1

    def destroy_virtual_display(self) -> None:
        self.destroyed += 1

    def capture_frame(self):
        raise NotImplementedError


class FakeInputInjectorForRunner:
    instances: list["FakeInputInjectorForRunner"] = []

    def __init__(self, _config) -> None:
        self.closed = False
        FakeInputInjectorForRunner.instances.append(self)

    def close(self) -> None:
        self.closed = True


class FakeSession:
    """Stands in for WebRtcSession: start() succeeds instantly, and
    wait_closed() resolves only when the test calls simulate_disconnect()
    (mirroring WebRtcSession._on_connection_state_change firing on its own,
    with nobody having called request_stop())."""

    instances: list["FakeSession"] = []

    def __init__(self, _display_server, _input_injector, _display_config) -> None:
        self.started = False
        self.closed = False
        self._closed_event = asyncio.Event()
        FakeSession.instances.append(self)

    async def start(self, _transport) -> None:
        self.started = True

    async def wait_closed(self) -> None:
        await self._closed_event.wait()

    async def close(self) -> None:
        self.closed = True
        self._closed_event.set()

    def simulate_disconnect(self) -> None:
        self._closed_event.set()


def test_disconnect_reconnects_without_tearing_down_display():
    """Covers the actual feature request: unplugging/closing the app should
    drop back to 'waiting for iPad', not require pressing Start again — the
    virtual display and input injector should stay up across a reconnect,
    only torn down on an explicit request_stop()."""

    async def body():
        FakeUsbTransport.instances.clear()
        FakeInputInjectorForRunner.instances.clear()
        FakeSession.instances.clear()
        display_server = FakeDisplayServerForRunner()
        states: list[tuple[State, str]] = []

        runner = HostRunner(
            display_config=None,
            on_status=lambda e: states.append((e.state, e.detail)),
        )

        async def fake_choose_transport(_config):
            return FakeUsbTransport()

        with (
            patch("host.runner.X11DisplayServer.cleanup_stale_virtual_outputs", return_value=[]),
            patch("host.runner.choose_transport", side_effect=fake_choose_transport),
            patch("host.runner.choose_display_server", return_value=display_server),
            patch("host.runner.InputInjector", FakeInputInjectorForRunner),
            patch("host.runner.WebRtcSession", FakeSession),
        ):
            run_task = asyncio.ensure_future(runner.run())
            await asyncio.sleep(0.05)  # let the first session connect

            assert len(FakeSession.instances) == 1
            assert FakeSession.instances[0].started
            assert (State.CONNECTED, "FakeUsbTransport") in states

            FakeSession.instances[0].simulate_disconnect()
            await asyncio.sleep(0.05)  # let it loop back and reconnect

            assert len(FakeSession.instances) == 2, "should start a new session, not reuse the dead one"
            assert FakeSession.instances[1].started
            assert display_server.created == 1, "virtual display must not be recreated on reconnect"
            assert display_server.destroyed == 0, "virtual display must not be torn down on a mere disconnect"
            assert any(
                state is State.WAITING and "disconnect" in detail.lower() for state, detail in states
            ), "must report back to waiting, not idle, on disconnect"

            runner.request_stop()
            await asyncio.wait_for(run_task, timeout=1)

        assert display_server.created == 1
        assert display_server.destroyed == 1
        assert FakeInputInjectorForRunner.instances[0].closed
        assert states[-1] == (State.IDLE, "")

    asyncio.run(body())


class FailingThenDisconnectTrackingTransport(Transport):
    """connect() always raises — stands in for a UsbTransport whose iproxy
    tunnel never came up (device still enumerating, etc). Tracks whether
    disconnect() got called so the test can catch a leak: if nothing cleans
    up a transport whose connect() failed, its iproxy subprocess (or
    whatever resource it opened) is left running."""

    def __init__(self) -> None:
        self.disconnected = False

    async def is_available(self) -> bool:
        return True

    async def connect(self) -> None:
        raise RuntimeError("Could not connect to the iPad's signaling server.")

    async def disconnect(self) -> None:
        self.disconnected = True

    async def send_signal(self, message: dict) -> None:
        raise NotImplementedError

    async def receive_signal(self) -> dict:
        raise NotImplementedError


def test_establish_transport_disconnects_on_failed_connect():
    """Covers a resource leak hit live: a transport whose connect() raised
    (retries exhausted) was never disconnect()ed, leaking its iproxy
    subprocess — the next attempt then failed immediately with "Address
    already in use" stacked on top of the original error."""

    async def body():
        transport = FailingThenDisconnectTrackingTransport()
        runner = HostRunner(display_config=None, on_status=lambda e: None)

        async def fake_choose_transport(_config):
            return transport

        with (
            patch("host.runner.choose_transport", side_effect=fake_choose_transport),
        ):
            config = HostConfig(display=None)
            try:
                await asyncio.wait_for(runner._establish_transport(config), timeout=1)
                raised = False
            except RuntimeError:
                raised = True

        assert raised, "the original connect failure must still propagate"
        assert transport.disconnected, "the failed transport must still be cleaned up"

    asyncio.run(body())


def test_usb_unplug_forces_disconnect_even_if_webrtc_stays_connected():
    """Covers the actual feature request: WebRTC's ICE can keep a session's
    media flowing over Wi-Fi even after the USB cable is unplugged, if the
    iPad happens to share a LAN with this host — confirmed live (video kept
    streaming for minutes after an unplug). A user who connected over USB
    may want unplugging it to always mean "disconnected" rather than a
    silent continue-over-Wi-Fi, so HostRunner polls USB presence and forces
    the session closed the moment it's gone, independent of whether
    WebRtcSession's own wait_closed() ever fires on its own."""

    async def body():
        FakeUsbTransport.instances.clear()
        FakeInputInjectorForRunner.instances.clear()
        FakeSession.instances.clear()
        display_server = FakeDisplayServerForRunner()
        states: list[tuple[State, str]] = []
        usb_gone = asyncio.Event()
        watchdog_calls = 0

        runner = HostRunner(
            display_config=None,
            on_status=lambda e: states.append((e.state, e.detail)),
        )

        async def fake_choose_transport(_config):
            return FakeUsbTransport()

        async def fake_wait_until_usb_unavailable():
            # Only the first session's watchdog actually fires — otherwise,
            # since `usb_gone` stays set, every subsequent reconnected
            # session's watchdog would also resolve immediately and the
            # runner would reconnect in a tight loop forever. Realistically
            # the next _establish_transport() would stop choosing USB once
            # it's actually gone; that re-selection is covered separately by
            # test_switches_from_wifi_to_usb_when_cable_appears_mid_wait.
            nonlocal watchdog_calls
            watchdog_calls += 1
            if watchdog_calls == 1:
                await usb_gone.wait()
            else:
                await asyncio.Event().wait()

        with (
            patch("host.runner.X11DisplayServer.cleanup_stale_virtual_outputs", return_value=[]),
            patch("host.runner.choose_transport", side_effect=fake_choose_transport),
            patch("host.runner.choose_display_server", return_value=display_server),
            patch("host.runner.InputInjector", FakeInputInjectorForRunner),
            patch("host.runner.WebRtcSession", FakeSession),
            patch("host.runner.UsbTransport", FakeUsbTransport),
            patch("host.runner._wait_until_usb_unavailable", side_effect=fake_wait_until_usb_unavailable),
        ):
            run_task = asyncio.ensure_future(runner.run())
            await asyncio.sleep(0.05)  # let the first session connect

            assert len(FakeSession.instances) == 1
            first_session = FakeSession.instances[0]
            assert not first_session.closed

            # Simulate the physical unplug: the watchdog notices, but
            # wait_closed() never resolves on its own — mirroring the live
            # case where the WebRTC connection kept working over Wi-Fi.
            usb_gone.set()
            await asyncio.sleep(0.05)

            assert first_session.closed, "must force-close even though wait_closed() never fired"
            assert len(FakeSession.instances) == 2, "must loop back and start a new session"

            runner.request_stop()
            await asyncio.wait_for(run_task, timeout=1)

        assert states[-1] == (State.IDLE, "")

    asyncio.run(body())
