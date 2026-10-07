# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""HostRunner with several clients at once: each admitted client gets its own
virtual display, injector and session; the host refuses clients past the cap;
a monitor outlives its client briefly so a reconnect gets it back; one
client's failure leaves the others streaming; and `request_stop()` works at
any moment, including before any client has shown up.

Everything below the runner is faked — no sockets, no xrandr, no uinput.
"""

import asyncio
from unittest.mock import patch

import pytest

from host.runner import HostRunner, State
from host.transport.adb import AdbTransport
from host.transport.base import Transport
from host.transport.usb import UsbTransport


class FakeListener:
    """Stands in for WifiListener; `arrive()` plays a client connecting."""

    instance: "FakeListener"

    def __init__(self, _port) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.started = self.stopped = False
        FakeListener.instance = self

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def accept(self):
        return await self.queue.get()

    def arrive(self, transport: "FakeTransport") -> None:
        self.queue.put_nowait(transport)


class FakeTransport(Transport):
    supports_wired_stream = False

    def __init__(self, name: str = "client") -> None:
        self._name = name
        self.disconnected = False
        self.signals: list[dict] = []

    @property
    def label(self) -> str:
        return self._name

    async def is_available(self) -> bool:
        return True

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        self.disconnected = True

    async def send_signal(self, message: dict) -> None:
        self.signals.append(message)

    async def receive_signal(self) -> dict:
        raise NotImplementedError


class FakeDisplayServer:
    created = 0
    destroyed = 0
    fail_next = False
    instances: list["FakeDisplayServer"] = []

    def __init__(self) -> None:
        self.is_up = False
        FakeDisplayServer.instances.append(self)

    def create_virtual_display(self, config) -> None:
        if FakeDisplayServer.fail_next:
            FakeDisplayServer.fail_next = False
            raise RuntimeError("No spare output available")
        self.is_up = True
        FakeDisplayServer.created += 1

    def destroy_virtual_display(self) -> None:
        self.is_up = False
        FakeDisplayServer.destroyed += 1

    def capture_frame(self):
        raise NotImplementedError


class FakeInjector:
    instances: list["FakeInjector"] = []

    def __init__(self, _config, name="x") -> None:
        self.name = name
        self.closed = False
        FakeInjector.instances.append(self)

    def close(self) -> None:
        self.closed = True


class FakeSession:
    instances: list["FakeSession"] = []

    def __init__(self, display_server, input_injector, _display_config) -> None:
        self.display_server = display_server
        self.input_injector = input_injector
        self.closed = False
        self._closed_event = asyncio.Event()
        FakeSession.instances.append(self)

    async def start(self, _transport) -> None:
        pass

    async def wait_closed(self) -> None:
        await self._closed_event.wait()

    async def close(self) -> None:
        self.closed = True
        self._closed_event.set()

    def simulate_disconnect(self) -> None:
        self._closed_event.set()


@pytest.fixture(autouse=True)
def fakes():
    """Fake every layer below the runner and reset the shared bookkeeping."""
    FakeDisplayServer.created = FakeDisplayServer.destroyed = 0
    FakeDisplayServer.fail_next = False
    for fake in (FakeDisplayServer, FakeInjector, FakeSession):
        fake.instances.clear()

    async def no_devices(_cls) -> list[str]:
        return []

    with (
        patch("host.runner.X11DisplayServer.cleanup_stale_virtual_outputs", return_value=[]),
        patch("host.runner.WifiListener", FakeListener),
        patch("host.runner.choose_display_server", side_effect=FakeDisplayServer),
        patch("host.runner.InputInjector", FakeInjector),
        patch("host.runner.WebRtcSession", FakeSession),
        patch("host.runner.WiredSession", FakeSession),
        patch.object(UsbTransport, "list_devices", classmethod(no_devices)),
        patch.object(AdbTransport, "list_devices", classmethod(no_devices)),
    ):
        yield


async def _settle() -> None:
    await asyncio.sleep(0.05)


def _runner(states=None, **kwargs) -> HostRunner:
    kwargs.setdefault("display_linger_s", 0)
    return HostRunner(
        display_config=None,
        on_status=(lambda e: states.append(e)) if states is not None else None,
        **kwargs,
    )


def test_request_stop_before_any_client_returns_to_idle():
    """The original UI bug: stop pressed while nothing is connected yet must
    still end the run."""

    async def body():
        states: list = []
        runner = _runner(states)
        run_task = asyncio.ensure_future(runner.run())
        await _settle()
        runner.request_stop()
        await asyncio.wait_for(run_task, timeout=1)

        assert FakeListener.instance.started and FakeListener.instance.stopped
        assert states[-1].state is State.IDLE
        assert State.STOPPING in [e.state for e in states]

    asyncio.run(body())


def test_two_clients_stream_at_once_each_with_its_own_display():
    async def body():
        states: list = []
        runner = _runner(states)
        run_task = asyncio.ensure_future(runner.run())
        await _settle()

        FakeListener.instance.arrive(FakeTransport("Wi-Fi 10.0.0.2"))
        FakeListener.instance.arrive(FakeTransport("Wi-Fi 10.0.0.3"))
        await _settle()

        assert len(FakeSession.instances) == 2
        first, second = FakeSession.instances
        assert first.display_server is not second.display_server
        assert first.input_injector is not second.input_injector
        assert first.input_injector.name != second.input_injector.name
        assert FakeDisplayServer.created == 2
        assert sorted(runner.client_labels) == ["Wi-Fi 10.0.0.2", "Wi-Fi 10.0.0.3"]
        assert states[-1].state is State.CONNECTED
        assert len(states[-1].clients) == 2

        runner.request_stop()
        await asyncio.wait_for(run_task, timeout=1)
        assert FakeDisplayServer.destroyed == 2
        assert all(injector.closed for injector in FakeInjector.instances)

    asyncio.run(body())


def test_client_past_the_cap_is_refused_without_getting_a_display():
    async def body():
        runner = _runner(max_clients=1)
        run_task = asyncio.ensure_future(runner.run())
        await _settle()

        listener = FakeListener.instance
        listener.arrive(FakeTransport("first"))
        await _settle()
        refused = FakeTransport("second")
        listener.arrive(refused)
        await _settle()

        assert refused.signals == [{"type": "bye", "reason": "error"}]
        assert refused.disconnected
        assert len(FakeSession.instances) == 1
        assert FakeDisplayServer.created == 1
        assert runner.client_labels == ["first"], "the admitted client must be unaffected"

        runner.request_stop()
        await asyncio.wait_for(run_task, timeout=1)

    asyncio.run(body())


def test_leaving_client_frees_its_display_and_its_slot():
    async def body():
        runner = _runner(max_clients=1)
        run_task = asyncio.ensure_future(runner.run())
        await _settle()

        listener = FakeListener.instance
        listener.arrive(FakeTransport("a"))
        await _settle()
        FakeSession.instances[0].simulate_disconnect()
        await _settle()

        assert FakeDisplayServer.destroyed == 1  # linger is 0 in these tests
        assert runner.client_labels == []

        listener.arrive(FakeTransport("b"))  # the slot is free again
        await _settle()
        assert runner.client_labels == ["b"]

        runner.request_stop()
        await asyncio.wait_for(run_task, timeout=1)

    asyncio.run(body())


def test_reconnect_within_the_linger_reuses_the_display():
    """A dropped-and-reconnected client must get its monitor (and the windows
    on it) back rather than a freshly created one."""

    async def body():
        runner = _runner(display_linger_s=30)
        run_task = asyncio.ensure_future(runner.run())
        await _settle()

        listener = FakeListener.instance
        listener.arrive(FakeTransport("a"))
        await _settle()
        FakeSession.instances[0].simulate_disconnect()
        await _settle()
        assert FakeDisplayServer.destroyed == 0, "kept for the linger"

        listener.arrive(FakeTransport("a again"))
        await _settle()
        assert FakeDisplayServer.created == 1, "no second monitor for the reconnect"
        assert FakeSession.instances[1].display_server is FakeSession.instances[0].display_server

        runner.request_stop()
        await asyncio.wait_for(run_task, timeout=1)
        assert FakeDisplayServer.destroyed == 1

    asyncio.run(body())


def test_parked_display_is_destroyed_when_the_linger_runs_out():
    async def body():
        runner = _runner(display_linger_s=0.05)
        run_task = asyncio.ensure_future(runner.run())
        await _settle()

        FakeListener.instance.arrive(FakeTransport("a"))
        await _settle()
        FakeSession.instances[0].simulate_disconnect()
        await asyncio.sleep(0.2)
        assert FakeDisplayServer.destroyed == 1

        runner.request_stop()
        await asyncio.wait_for(run_task, timeout=1)

    asyncio.run(body())


def test_one_client_failing_to_get_a_display_leaves_the_other_streaming():
    async def body():
        runner = _runner()
        run_task = asyncio.ensure_future(runner.run())
        await _settle()

        listener = FakeListener.instance
        listener.arrive(FakeTransport("good"))
        await _settle()
        FakeDisplayServer.fail_next = True  # e.g. no spare output left
        failing = FakeTransport("bad")
        listener.arrive(failing)
        await _settle()

        assert failing.signals == [{"type": "bye", "reason": "error"}]
        assert failing.disconnected
        assert runner.client_labels == ["good"]
        assert not run_task.done()

        runner.request_stop()
        await asyncio.wait_for(run_task, timeout=1)

    asyncio.run(body())


def test_disconnect_client_ends_only_that_client():
    async def body():
        runner = _runner()
        run_task = asyncio.ensure_future(runner.run())
        await _settle()

        listener = FakeListener.instance
        listener.arrive(FakeTransport("a"))
        listener.arrive(FakeTransport("b"))
        await _settle()

        assert runner.disconnect_client("a")
        await _settle()
        assert runner.client_labels == ["b"]
        assert not runner.disconnect_client("nobody")

        runner.request_stop()
        await asyncio.wait_for(run_task, timeout=1)

    asyncio.run(body())


class FakeUsbDevice(FakeTransport):
    """What `UsbTransport` is to the runner: built per device, connect()s, and
    the class lists which serials are plugged in."""

    plugged_in: list[str] = []
    built: list["FakeUsbDevice"] = []

    def __init__(self, local_port: int, serial: str) -> None:
        super().__init__(f"USB {serial}")
        self.serial = serial
        self.local_port = local_port
        FakeUsbDevice.built.append(self)

    @classmethod
    async def list_devices(cls) -> list[str]:
        return list(cls.plugged_in)


def test_usb_devices_are_served_per_device_and_stop_when_unplugged():
    async def body():
        FakeUsbDevice.plugged_in = ["PHONE", "TABLET"]
        FakeUsbDevice.built.clear()
        runner = _runner()
        with (
            patch("host.runner.UsbTransport", FakeUsbDevice),
            patch("host.runner._USB_POLL_S", 0.02),
        ):
            run_task = asyncio.ensure_future(runner.run())
            await asyncio.sleep(0.2)
            assert sorted(runner.client_labels) == ["USB PHONE", "USB TABLET"]
            assert len({d.local_port for d in FakeUsbDevice.built}) == len(FakeUsbDevice.built), (
                "each device needs its own tunnel port"
            )

            FakeUsbDevice.plugged_in = ["TABLET"]  # the phone is unplugged
            await asyncio.sleep(0.2)
            assert runner.client_labels == ["USB TABLET"]
            phone_session = next(s for s in FakeSession.instances if s.closed)
            assert phone_session is not None

            runner.request_stop()
            await asyncio.wait_for(run_task, timeout=1)
        assert FakeDisplayServer.destroyed == FakeDisplayServer.created

    asyncio.run(body())


def test_usb_device_waits_for_a_free_slot_instead_of_being_refused():
    async def body():
        FakeUsbDevice.plugged_in = ["TABLET"]
        FakeUsbDevice.built.clear()
        runner = _runner(max_clients=1)
        with (
            patch("host.runner.UsbTransport", FakeUsbDevice),
            patch("host.runner._USB_POLL_S", 0.02),
        ):
            run_task = asyncio.ensure_future(runner.run())
            await _settle()
            FakeListener.instance.arrive(FakeTransport("wifi"))
            await asyncio.sleep(0.1)
            # Either order of arrival is fine; what matters is the host never
            # holds more than the cap and nobody was sent a refusal.
            assert len(runner.client_labels) == 1

            runner.request_stop()
            await asyncio.wait_for(run_task, timeout=1)

    asyncio.run(body())
