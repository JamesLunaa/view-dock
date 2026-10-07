# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""The host's own LAN addresses, for showing the user what to type into the
app's "Connect over Wi-Fi" field."""

import re
import socket
import subprocess

# Interfaces that hold an address a phone on the Wi-Fi can't reach.
_VIRTUAL_PREFIXES = ("lo", "docker", "br-", "veth", "virbr", "tailscale", "tun", "tap", "vmnet", "zt")
_ADDR_RE = re.compile(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/")


def _default_route_address() -> str | None:
    """The address the OS would use to reach the internet — almost always the
    one on the Wi-Fi/Ethernet network. Connecting a UDP socket sends nothing."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))  # TEST-NET-1, never routed anywhere
            address = sock.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith("127.") or address == "0.0.0.0" else address


def lan_addresses() -> list[str]:
    """Likely-reachable IPv4 addresses of this machine, best guess first."""
    found: list[str] = []
    primary = _default_route_address()
    if primary:
        found.append(primary)
    try:
        result = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "scope", "global"],
            capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return found
    for line in result.stdout.splitlines():
        match = _ADDR_RE.match(line)
        if match and not match.group(1).startswith(_VIRTUAL_PREFIXES) and match.group(2) not in found:
            found.append(match.group(2))
    return found


def wifi_address_text(port: int) -> str:
    """One line for a UI: where a client should connect over Wi-Fi."""
    addresses = lan_addresses()
    if not addresses:
        return "Wi-Fi address: not on a network"
    return f"Wi-Fi address: {' or '.join(addresses)} (port {port})"
