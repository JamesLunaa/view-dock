# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Covers the Android USB path: `AdbTransport` reuses `UsbTransport`'s
connect/retry logic but must build an `adb forward` tunnel, only treat a
device in the `device` state as usable, and list the usable devices by serial
so the runner can serve several at once.
"""

import asyncio
from unittest.mock import patch

import pytest

from host.transport.adb import AdbTransport, _is_ready_device_line
from host.transport.usb import UsbTransport


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


def test_serial_targets_that_device_in_every_adb_call():
    transport = AdbTransport(local_port=9001, device_port=9002, serial="R58M123ABC")
    assert transport._tunnel_argv() == ["adb", "-s", "R58M123ABC", "forward", "tcp:9001", "tcp:9002"]
    assert UsbTransport(local_port=9001, device_port=9002, serial="UDID1")._tunnel_argv() == [
        "iproxy", "-u", "UDID1", "9001", "9002",
    ]


def test_list_devices_returns_only_usable_serials():
    class FakeProc:
        returncode = 0

        async def communicate(self):
            out = b"List of devices attached\nAAA\tdevice\nBBB\tunauthorized\nCCC\tdevice product:x\n\n"
            return out, b""

    async def body():
        async def fake_exec(*_args, **_kwargs):
            return FakeProc()

        with patch("asyncio.create_subprocess_exec", fake_exec):
            assert await AdbTransport.list_devices() == ["AAA", "CCC"]
            assert await AdbTransport().is_available() is True

    asyncio.run(body())


def test_list_devices_empty_when_tool_missing():
    async def body():
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            assert await AdbTransport.list_devices() == []
            assert await UsbTransport.list_devices() == []

    asyncio.run(body())
