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
  `wifi.py` does LAN discovery/signaling; `usb.py` shells out to
  `iproxy` (from `libimobiledevice`) to open a usbmuxd TCP tunnel to a
  connected iPad, after which the same WebRTC session logic in `streaming/`
  runs over it.
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

Scaffolding only — interfaces and module boundaries are in place; the actual
capture/encode/stream/input-injection logic is not implemented yet.
