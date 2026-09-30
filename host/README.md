# host

Python server that runs on the Arch Linux machine. Creates a virtual display,
captures and encodes it, streams it to the iPad over WebRTC, and injects input
events received back from the iPad.

## Layout

- `displayserver/` — abstraction over the Linux display server. `base.py`
  defines the interface; `x11.py` is the phase 1 implementation (`xrandr` for
  the virtual output, `mss` for capture). A `wayland.py` implementation is
  planned for phase 2.
- `streaming/` — the `aiortc`-based WebRTC session: video track sourced from
  the display server capture, and the `control` data channel carrying
  `protocol/` messages (handshake, display info, stats).
- `transport/` — connection establishment for each physical transport.
  `wifi.py` runs a WebSocket signaling *server* that the iPad connects to
  directly over the LAN. `usb.py` shells out to `iproxy` (from
  `libimobiledevice`) to open a usbmuxd TCP tunnel and connects through it as
  a WebSocket *client* — `iproxy` owns the local port and relays to a port
  the iPad app listens on, so for USB the iPad must be the server, unlike
  Wi-Fi. Once connected, the same WebRTC session logic in `streaming/` runs
  over either.
- `input/` — injects `input_event` messages from the iPad into the X11 (or
  later Wayland) session via `uinput`.
- `config.py` — runtime configuration (virtual display resolution/refresh,
  transport preference).
- `main.py` — entrypoint: picks a transport, brings up the display server,
  and runs the WebRTC session.

## Requirements

- Arch Linux, X11 session (Wayland support is phase 2).
- System packages: `xorg-xrandr`, `ffmpeg`.
- For USB: `usbmuxd` + `libimobiledevice` (provides `iproxy`/`idevice_id`).
  **Use the AUR `-git` packages** (`usbmuxd-git`, `libimobiledevice-git`,
  `libusbmuxd-git`, `libplist-git`, `libimobiledevice-glue-git`) — Arch's
  official `libimobiledevice` (1.4.0 at time of writing) is too old to
  complete the lockdownd pairing handshake with iOS 17+/iPadOS 26+ and fails
  with `lockdown error -8` before the device ever shows a trust prompt. The
  `-git` packages `provide`/`conflict` the official ones, so `yay -S
  <packages above>` swaps them in place.
- Python 3.11+, deps in `requirements.txt`.

## Status

Implemented and **verified end-to-end on real hardware** (Wi-Fi and USB,
both transports, 2026-09-30): X11 virtual display (`xrandr` + `mss`),
`uinput` input injection, Wi-Fi signaling (WebSocket SDP/ICE exchange) with
the USB transport tunneling the same signaling over `iproxy`, and the WebRTC
session (video track, control data channel,
`hello`/`display_info`/`input_event`/`bye` handling).

Two extra `DisplayServer` implementations exist purely for testing on a
machine without a working `xf86-video-dummy` Xorg session (this dev machine
runs Wayland, where Xwayland can neither create xrandr virtual outputs nor
expose real desktop content to `mss` — captured frames come back all zero):
`displayserver/passthrough.py` (captures the real primary monitor — same
Wayland limitation applies) and `displayserver/test_pattern.py` (synthetic
animated frame, no capture at all — this is what was actually used to
validate the pipeline). Toggle with `VIEWDOCK_PASSTHROUGH_DISPLAY=1` /
`VIEWDOCK_TEST_PATTERN_DISPLAY=1` env vars; unset, `main.py` uses the real
`X11DisplayServer`.

Not yet done: adaptive bitrate from `stats` messages, mDNS discovery for
Wi-Fi, and Wayland support (phase 2). `create_virtual_display()` in
`x11.py` itself still hasn't been verified against a real Xorg session with
`xf86-video-dummy` configured — only exercised against Xwayland, which
correctly raises "no disconnected output available."
