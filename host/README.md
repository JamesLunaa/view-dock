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
- System packages: `xorg-xrandr`, `libimobiledevice` (provides `iproxy` and
  `usbmuxd`), `ffmpeg`.
- Python 3.11+, deps in `requirements.txt`.

## Status

Implemented: X11 virtual display (`xrandr` + `mss`), `uinput` input injection,
Wi-Fi signaling (WebSocket SDP/ICE exchange) with the USB transport tunneling
the same signaling over `iproxy`, and the WebRTC session (video track, control
data channel, `hello`/`display_info`/`input_event`/`bye` handling). Verified
with a scripted `aiortc` peer standing in for the iPad — full offer/answer
negotiation, handshake, and input round-trip all pass.

Not yet done: adaptive bitrate from `stats` messages, mDNS discovery for
Wi-Fi, and Wayland support (phase 2). `create_virtual_display()` requires a
disconnected output backed by `xf86-video-dummy` — a plain GPU-driven X
session (or Xwayland) has no spare connector to attach a synthetic mode to.
