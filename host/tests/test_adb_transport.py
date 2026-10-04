# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Covers the Android USB path: `AdbTransport` reuses `UsbTransport`'s
connect/retry logic but must build an `adb forward` tunnel, only treat a
device in the `device` state as usable, and be picked up by the runner's
wired-transport detection alongside the iOS one.
"""

import asyncio
from unittest.mock import patch

import pytest

from host.runner import _find_wired_transport, choose_transport
from host.config import HostConfig
from host.transport.adb import AdbTransport, _is_ready_device_line
from host.transport.usb import UsbTransport
from host.transport.wifi import WifiTransport


def test_tunnel_is_adb_forward_not_iproxy():
    transport = AdbTransport(local_port=9001, device_port=9002)
    assert transport._tunnel_argv() == ["adb", "forward", "tcp:9001", "tcp:9002"]
    assert UsbTransport(local_port=9001, device_port=9002)._tunnel_argv() == ["iproxy", "9001", "9002"]


@pytest.mark.parametrize(
    "line, ready",
    [
        ("R58M123ABC\tdevice", True),
        ("R58M123ABC\tdevice product:x model:V2352", True),
        ("R58M123ABC\tunauthorized", False),  # phone hasn't accepted the host's key
        ("R58M123ABC\toffline", False),
        ("List of devices attached", False),
        ("", False),
    ],
)
def test_only_device_state_counts_as_available(line, ready):
    assert _is_ready_device_line(line) is ready


def test_is_available_false_when_adb_missing():
    async def body():
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            assert await AdbTransport().is_available() is False

    asyncio.run(body())


class _Available:
    def __init__(self, available: bool) -> None:
        self._available = available

    def __call__(self):
        return self

    async def is_available(self) -> bool:
        return self._available


def test_runner_finds_adb_device_when_no_ios_device():
    async def body():
        with (
            patch("host.runner.UsbTransport", _Available(False)),
            patch("host.runner.AdbTransport", lambda: sentinel),
        ):
            sentinel = _Available(True)
            assert await _find_wired_transport() is sentinel

    asyncio.run(body())


def test_choose_transport_falls_back_to_wifi_with_nothing_attached():
    async def body():
        with (
            patch("host.runner.UsbTransport", _Available(False)),
            patch("host.runner.AdbTransport", _Available(False)),
        ):
            assert isinstance(await choose_transport(HostConfig(display=None)), WifiTransport)

    asyncio.run(body())
