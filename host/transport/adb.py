"""Android USB transport: tunnels a local TCP port to a matching port on the
phone/tablet via `adb forward`, the Android counterpart to `iproxy`.

Same shape as `UsbTransport`: the *host* connects as a WebSocket client
through the tunnel, so the Android app is the one listening on `device_port`
(see android/.../UsbSignaling.kt). That is why this subclasses `UsbTransport`
and only swaps out how the tunnel is created and how a device is detected —
the retry-until-the-app-is-open connect logic is identical.

Differences from `iproxy` worth knowing:
- `adb forward` is not a long-running process: it registers the forward with
  the adb server and exits immediately, so there is nothing to terminate on
  disconnect — the forward is removed explicitly instead.
- The forward accepts connections even while nothing listens on the device
  side (it just closes them), which `_connect_with_retry` already treats as
  "app not open yet".

Requires USB debugging enabled on the device and `adb` on PATH (Arch package:
`android-tools`).
"""

import asyncio
import logging

from host.transport.usb import UsbTransport

logger = logging.getLogger(__name__)


class AdbTransport(UsbTransport):
    # The Android app takes video over this tunnel directly (WebRTC's UDP media
    # can't ride `adb forward`, which is TCP-only), so a cable works without Wi-Fi.
    supports_wired_stream = True

    def _tunnel_argv(self) -> list[str]:
        return ["adb", "forward", f"tcp:{self._local_port}", f"tcp:{self._device_port}"]

    async def is_available(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "adb",
                "devices",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return False
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return False
        return any(_is_ready_device_line(line) for line in stdout.decode(errors="replace").splitlines())

    async def disconnect(self) -> None:
        await super().disconnect()
        await self._remove_forward()

    async def _remove_forward(self) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "adb",
                "forward",
                "--remove",
                f"tcp:{self._local_port}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return
        await proc.wait()


def _is_ready_device_line(line: str) -> bool:
    """`adb devices` lists `<serial>\\t<state>`; only `device` is usable —
    `unauthorized` means the phone hasn't accepted this host's RSA key yet
    and `offline` means adb can't talk to it, neither can carry a forward."""
    parts = line.split()
    return len(parts) >= 2 and parts[1] == "device"
