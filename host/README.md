# host

Python server that runs on the Arch Linux machine. Creates a virtual display,
captures and encodes it, streams it to the iPad over WebRTC, and injects input
events received back from the iPad.

## Layout

- `displayserver/` — abstraction over the Linux display server. `base.py`
  defines the interface; `x11.py` is the phase 1 implementation (`xrandr` for
  the virtual output, `mss` for capture). Alongside it, `cursor.py`
  composites the pointer into captured frames (`mss` returns framebuffer
  only, so the cursor is otherwise invisible on the iPad) and
  `geometry_watch.py` re-resolves the capture rectangle when the desktop's
  display arrangement changes underneath a running session. A `wayland.py`
  implementation is planned for phase 2.
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
- `scripts/force-connector.sh` — forces a real GPU connector "connected" at
  the kernel/DRM level so the virtual display can attach to it with nothing
  plugged in. This is the path used on a real Xorg desktop; see "Real GPU
  output on an Xorg desktop" below.
- `xorg/dummy.conf` + `scripts/start-dummy-display.sh` — fallback for a
  machine whose main desktop is Wayland (where `xrandr` can't create virtual
  outputs at all): brings up a separate `xf86-video-dummy`-backed X server.
  See "Fallback: Wayland desktop" below.
- `config.py` — runtime configuration (virtual display resolution/refresh,
  transport preference) and `IPAD_PRESETS`, logical-point resolutions for
  current iPad models.
- `runner.py` — `HostRunner`: the transport → virtual display → WebRTC
  session lifecycle, pulled out of `main.py` so it can report state
  (idle/starting/waiting/connected/stopping) to a caller instead of only a
  log stream. `main.py`, `ui/`, and `gui/` all drive the same `HostRunner`.
  Also switches from Wi-Fi to USB mid-session if a cable shows up after a
  session already started on Wi-Fi — `choose_transport()` only checks once.
- `presets.py` — the device-resolution preset list (built from
  `config.IPAD_PRESETS`), shared by `ui/` and `gui/` so they never drift.
- `async_loop_thread.py` — runs `HostRunner`'s asyncio loop on a background
  thread; shared by `ui/` and `gui/`, which each own the main thread for
  their own toolkit's event loop (curses, Qt).
- `main.py` — CLI entrypoint: runs a `HostRunner` to completion, logging its
  state transitions.
- `ui/` — terminal UI (`python -m host.ui`): start/stop, a device-resolution
  picker, and a live log pane, so a session doesn't mean re-typing
  `force-connector.sh` + env vars + `python -m host.main` by hand. Works
  anywhere there's a terminal, including over SSH with no X server. See
  "Running it" below.
- `gui/` — KDE tray applet + window (`python -m host.gui`, needs `pip
  install PySide6`): `window.py` is the actual controls (resolution,
  start/stop, a live log) in a real window; `tray.py` owns the one
  `HostRunner`/background loop and the `QSystemTrayIcon` the window hides to.
  Closing the window defaults to minimizing to tray (configurable to Quit
  instead, from a dropdown in the window itself) — closing it doesn't end an
  active session either way unless you also choose Quit from the tray menu
  or set that preference. `gui/assets/icon.png` + `gui/viewdock-host.desktop.in`
  + `scripts/install-desktop-entry.sh`/`scripts/launch-gui.sh` are an
  application-menu launcher — "an app icon, no CLI needed" — see "Running
  it" below.

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

**Working end-to-end as a real extended display** (verified on hardware
2026-10-01, Arch + KDE Plasma on Xorg, iPad Air 11" M3 over USB): windows
drag from the built-in screen onto the iPad and render there live, with the
mouse cursor visible, at correct UI scale, and the capture follows when the
display arrangement is rearranged in KDE's settings.

Both transports work (Wi-Fi and USB); USB is preferred automatically when a
device is attached. Also implemented: `uinput` input injection, WebRTC video
track + `control` data channel with schema-validated
`hello`/`display_info`/`input_event`/`bye` messages.

**Known gap**: touch input on the iPad is forwarded and injected, but it
moves the *shared* X pointer rather than acting as a touchscreen bound to
the virtual display's region, so it isn't usable as direct touch control
yet. Video is unaffected. See TODO/TODO.md.

Not yet done: adaptive bitrate from `stats` messages, mDNS discovery for
Wi-Fi, Pencil pressure/hover, and Wayland support (phase 2).

## Running it

On an Xorg desktop with an iPad connected by cable:

```sh
# 1. Once per boot — make a spare GPU connector look plugged in.
./host/scripts/force-connector.sh HDMI-A-1

# 2a. KDE tray applet + window: resolution picker, start/stop, and a live log
#     in an actual window, plus a tray icon it can hide to (needs
#     `pip install PySide6` first). Install an application-menu launcher once
#     so this never needs a terminal at all:
./host/scripts/install-desktop-entry.sh
#     Then launch "view-dock Host" from your app menu like anything else. Or
#     run it directly:
DISPLAY=:0 python -m host.gui

# 2b. Or the terminal UI: same idea, no extra dependency, works over SSH.
DISPLAY=:0 python -m host.ui

# 2c. Or the raw CLI, same as before. USB is auto-preferred when a device is
#     attached. Size it in the iPad's LOGICAL points, not physical pixels
#     (see below).
DISPLAY=:0 VIEWDOCK_DISPLAY_WIDTH=1180 VIEWDOCK_DISPLAY_HEIGHT=820 \
    python -m host.main
```

Then open the app on the iPad — it listens for USB automatically. In the
GUI, Stop from the window or tray menu, then Quit from the tray menu (closing
the window alone just hides it to tray by default — see "Closing the window"
below); in the TUI, `x` (or `q` to stop-and-quit); on the CLI, Ctrl+C —
either way the virtual output is torn down cleanly. A plain `kill` (SIGTERM)
now also tears down cleanly on the CLI; only `kill -9` skips it (the GUI/TUI
don't install a SIGTERM handler of their own — quit them through their own
UI, not `kill`).

The force-connector step (1) still has to run before any of these; the
GUI/TUI detect a missing spare output and say which disconnected XRandR
outputs are candidates rather than failing silently.

### Closing the window

The window's close button defaults to minimizing to tray rather than ending
the session — click the tray icon (or "Show window" from its right-click
menu) to bring it back. Change this from the dropdown at the bottom of the
window itself ("When closing this window: Minimize to tray / Quit"); the
choice persists across restarts (stored via `QSettings`, `~/.config/view-dock/
host-gui.conf`). Either way, actually ending a running session needs Stop
(window or tray menu) before Quit — closing the window, even set to "Quit",
tears down a live session the same clean way Stop does first.

### Sizing: use logical points, not physical pixels

Set the virtual display to the iPad's **logical point** resolution, not its
pixel resolution. An iPad Air 11" is 2360x1640 pixels but 1180x820 points
(a 2x retina panel). X11 renders UI at ~96 DPI with no per-output scaling
available on X11 (KDE's "Global scale" is global, so raising it would
distort the built-in screen too) — drive it at 2360x1640 and every toolbar
and glyph comes out at half its intended physical size. At 1180x820 the
iPad upscales 2x and everything lands correctly.

`cvt` rounds widths to a multiple of 8, so 1180 becomes 1184 — a 0.3%
aspect difference, not visible.

### Real GPU output on an Xorg desktop

`scripts/force-connector.sh` writes `on` to a DRM connector's debugfs
`force` file. This matters for a reason that isn't obvious: forcing a mode
at the **XRandR** level alone does produce a capturable region, but KDE's
kscreen decides what counts as a real screen from the **kernel DRM**
connector state, so the desktop refuses to place windows there — you get a
black rectangle you cannot drag anything onto. Forcing at the DRM level
makes it a real monitor to the whole stack.

Caveats worth knowing:

- **Not persistent.** debugfs resets on reboot. For a permanent setup, add
  `video=HDMI-A-1:e` to the kernel command line instead.
- The DRM connector name (`HDMI-A-1`) differs from the XRandR output name
  (`HDMI-1`) for the same port.
- Some drivers accept an XRandR-forced mode but keep reporting the output
  `disconnected` (confirmed on Intel), so `displayserver/x11.py` keys off
  "has no active geometry" rather than the connected/disconnected word when
  picking a spare output.
- KDE may re-lay-out displays on its own once it notices the new screen.
  Position both explicitly and atomically if it lands somewhere odd:
  `kscreen-doctor output.eDP-1.position.0,0 output.HDMI-1.position.1920,0`

### Fallback: Wayland desktop

If your main desktop is Wayland, `xrandr` can't create virtual outputs and
`mss` can't capture real content at all — Xwayland is a compatibility shim,
not a real X server, and returns all-zero frames. Options:

1. **Separate X server**: `host/scripts/start-dummy-display.sh` starts an
   isolated `xf86-video-dummy` X server on `:1`:
   ```sh
   ./host/scripts/start-dummy-display.sh
   DISPLAY=:1 VIEWDOCK_DISPLAY_WIDTH=1024 VIEWDOCK_DISPLAY_HEIGHT=768 \
       python -m host.main
   ```
   It is genuinely separate from your desktop (different VT), so it has no
   content of its own — launch apps into it with `DISPLAY=:1 <app>`, and
   prefer non-KDE apps (KDE ones may hang waiting on session D-Bus services
   that a bare second session doesn't have; `konsole` did). You cannot drag
   existing windows there, and input goes to whichever session holds VT
   focus — i.e. your real desktop. Video works fully.
2. **No real content**: `VIEWDOCK_PASSTHROUGH_DISPLAY=1` (captures the real
   primary monitor — blocked the same way on Wayland, kept for real Xorg)
   or `VIEWDOCK_TEST_PATTERN_DISPLAY=1` (synthetic animated frame, no
   capture at all). See `displayserver/passthrough.py` /
   `displayserver/test_pattern.py`.

The `xf86-video-dummy` build here hardcodes a 4 MB framebuffer and silently
ignores its own `VideoRam` option (confirmed via `strings dummy_drv.so`),
capping usable size at roughly 1024x768 shared across every enabled `DUMMY*`
output. Also: disabling and re-enabling a `DUMMY*` output reallocates its
framebuffer without zeroing it, so stale content can reappear until
something repaints — a driver quirk, not a bug here.

## Reconnecting after a drop

Unplugging the cable, killing the app, or any other disconnect that never
sends a clean `bye` loops the session back to waiting for a new connection
instead of tearing the whole thing down — the virtual display and input
injector stay up, so reconnecting (replugging, reopening the app) doesn't
need the UI restarted. Detection isn't instant: it rides aioice's ICE
consent-freshness checks (RFC 7675), tuned down from aioice's own defaults
(~30s) via `VIEWDOCK_ICE_CONSENT_INTERVAL` (default `1.0`, seconds between
checks) and `VIEWDOCK_ICE_CONSENT_FAILURES` (default `2`, consecutive misses
before giving up) in `streaming/webrtc_session.py` — in practice a few
seconds, not the ~2s the naive `interval x failures` multiplication
suggests, since each check also waits for a STUN response timeout per
candidate pair (see that file's comment). Lower them further for a snappier
reaction at the cost of more sensitivity to brief network hiccups falsely
registering as a drop.

**USB is a special case.** WebRTC's ICE picks whatever candidate pair
actually works, independent of which transport carried the signaling — if
the iPad shares a LAN with this host, unplugging the USB cable alone doesn't
necessarily break anything, since the same video/data can keep flowing over
Wi-Fi (confirmed live: it kept streaming for minutes after an unplug).
That's a reasonable feature on its own, but connecting over USB specifically
usually means you want unplugging it to mean "disconnected." `HostRunner`
polls the device's physical USB presence while connected via USB and forces
the session closed the instant it disappears, regardless of whether the
WebRTC connection itself is still technically alive.

## Troubleshooting

- **Virtual display shows a slice of another monitor.** The capture
  rectangle moved. This is handled automatically now
  (`displayserver/geometry_watch.py`); if it persists, restart the host.
- **`BadName` / `RRCreateMode` on startup.** Mode names are PID-suffixed, so
  this shouldn't happen from a normal prior run anymore — both `HostRunner`
  (used by `main.py` and `ui/`) sweep up any leftover `viewdock_*` mode
  before creating a new one. If it still happens, a `kill -9`/crash left
  something behind that the sweep couldn't see; `xrandr --delmode <output>
  <mode>` then `xrandr --rmmode <mode>` clears it manually.
- **No cursor on the iPad.** The overlay self-disables and logs a warning if
  XFixes is unavailable; check host output.
- **USB stays on "waiting for iPad" after plugging in.** Normal if the app
  isn't open yet — a device shows up as USB-paired well before anything is
  listening on the tunneled port, and the host now retries patiently and
  indefinitely for exactly this gap rather than giving up after a few
  seconds. Open (or foreground) the app and grant Local Network permission
  (Settings > Privacy & Security > Local Network) if it still doesn't
  connect. Note that older builds of the app stop listening after a single
  failed connection attempt and need a relaunch; see TODO/TODO.md.

## Tests

```sh
python -m pytest host/tests/
```
