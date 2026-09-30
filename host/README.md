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
- `xorg/dummy.conf` + `scripts/start-dummy-display.sh` — brings up a real,
  separate `xf86-video-dummy`-backed X server for the virtual display on a
  machine whose main desktop is Wayland (where `xrandr` can't create virtual
  outputs at all). See "Testing on a Wayland desktop" below.
- `config.py` — runtime configuration (virtual display resolution/refresh,
  transport preference).
- `main.py` — entrypoint: picks a transport, brings up the display server,
  and runs the WebRTC session.

## Requirements

- Arch Linux, X11 session (Wayland support is phase 2).
- System packages: `xorg-server`, `xorg-xrandr`, `xf86-video-dummy`, `ffmpeg`.
- For USB: `usbmuxd` + `libimobiledevice` (provides `iproxy`/`idevice_id`).
  **Use the AUR `-git` packages** (`usbmuxd-git`, `libimobiledevice-git`,
  `libusbmuxd-git`, `libplist-git`, `libimobiledevice-glue-git`) — Arch's
  official `libimobiledevice` (1.4.0 at time of writing) is too old to
  complete the lockdownd pairing handshake with iOS 17+/iPadOS 26+ and fails
  with `lockdown error -8` before the device ever shows a trust prompt. The
  `-git` packages `provide`/`conflict` the official ones, so `yay -S
  <packages above>` swaps them in place.
  - **Side effect**: `libplist-git` bumps the library's SONAME (`.so.4` →
    `.so.12`), which breaks any already-installed app still linked against
    the old one — on KDE this includes `konsole` (via `kio-extras`' device
    support) and likely other apps that touch `libplist`. Fix:
    `sudo ln -s /usr/lib/libplist-2.0.so.12 /usr/lib/libplist-2.0.so.4`.
- Python 3.11+, deps in `requirements.txt`.

## Status

Implemented and **verified end-to-end on real hardware** (Wi-Fi and USB,
both transports, real X11 desktop content — not a synthetic test pattern —
2026-10-01): X11 virtual display (`xrandr` + `mss`), `uinput` input
injection, Wi-Fi signaling (WebSocket SDP/ICE exchange) with the USB
transport tunneling the same signaling over `iproxy`, and the WebRTC session
(video track, control data channel,
`hello`/`display_info`/`input_event`/`bye` handling).

**Known limitation**: touch input from the iPad currently lands on whatever
session holds real VT/input focus, not necessarily the session being
streamed — see "Testing on a Wayland desktop" below and TODO/TODO.md. Video
works regardless.

Not yet done: adaptive bitrate from `stats` messages, mDNS discovery for
Wi-Fi, and Wayland support (phase 2).

## Testing on a Wayland desktop

If your main desktop is Wayland (not X11), `xrandr` can't create virtual
outputs and `mss` can't capture real content at all — Xwayland is a
compatibility shim, not a real X server (see git history for how this was
discovered: captured frames came back all zero). Two options:

1. **Real content, no touch control** (what's actually been verified): run
   a second, isolated X server on a separate display number via
   `host/scripts/start-dummy-display.sh`, then point the host at it:
   ```sh
   ./host/scripts/start-dummy-display.sh
   DISPLAY=:1 VIEWDOCK_DISPLAY_WIDTH=1024 VIEWDOCK_DISPLAY_HEIGHT=768 \
       python -m host.main
   ```
   This is a genuinely separate session from your desktop (different VT),
   so it needs its own content — launch apps with `DISPLAY=:1 <app>`.
   Non-KDE-dependent apps are safest (KDE apps may hang waiting on session
   D-Bus services that don't exist on this bare second session — `konsole`
   did this; not investigated further since it's not the actual goal). The
   video pipeline works fully; touch input goes to your *real* desktop
   instead, since that's whichever session holds VT focus — fixing that
   requires attaching the dummy output to your real desktop's own X11
   session instead (which requires switching your daily session from
   Wayland to Xorg — a bigger, deliberately deferred task, see
   TODO/TODO.md).
2. **No real content**: `VIEWDOCK_PASSTHROUGH_DISPLAY=1` (captures your real
   primary monitor — blocked the same way as above on Wayland, kept for a
   real Xorg session) or `VIEWDOCK_TEST_PATTERN_DISPLAY=1` (synthetic
   animated frame, no capture at all) env vars — see
   `displayserver/passthrough.py` / `displayserver/test_pattern.py`.

A quirk hit while testing: disabling and re-enabling a `DUMMY*` output
reallocates its framebuffer, and the driver doesn't zero it — stale content
from before the reset can reappear until something repaints. Not a bug in
this codebase, just how the dummy driver behaves.
