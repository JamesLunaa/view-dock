# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

from unittest.mock import patch

from host import netinfo

_IP_OUTPUT = """\
2: wlan0    inet 192.168.1.20/24 brd 192.168.1.255 scope global dynamic wlan0\\       valid_lft 1000sec
3: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0\\       valid_lft forever
4: enp3s0    inet 10.0.0.5/24 brd 10.0.0.255 scope global enp3s0\\       valid_lft forever
"""


def _fake_run(stdout):
    return lambda *a, **k: type("R", (), {"stdout": stdout})()


def test_default_route_address_comes_first_and_virtual_interfaces_are_skipped():
    with (
        patch.object(netinfo, "_default_route_address", return_value="192.168.1.20"),
        patch("subprocess.run", _fake_run(_IP_OUTPUT)),
    ):
        assert netinfo.lan_addresses() == ["192.168.1.20", "10.0.0.5"]


def test_text_shows_address_and_port():
    with patch.object(netinfo, "lan_addresses", return_value=["192.168.1.20"]):
        assert netinfo.wifi_address_text(8765) == "Wi-Fi address: 192.168.1.20 (port 8765)"


def test_text_when_offline():
    with patch.object(netinfo, "lan_addresses", return_value=[]):
        assert "not on a network" in netinfo.wifi_address_text(8765)
