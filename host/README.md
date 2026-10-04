# host

Python server that runs on the Arch Linux machine. Creates a virtual display,
captures and encodes it, streams it to the iPad or an Android device (WebRTC,
or a plain H.264 stream over the Android USB tunnel), and injects input
events received back from the device.

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
  Wi-Fi. `adb.py` is the Android equivalent of `usb.py`: same shape (the app
  listens, the host connects through the tunnel) but via `adb forward`.
  Once connected, the iPad paths and Wi-Fi run the same WebRTC session logic
  in `streaming/`; the Android USB path instead streams H.264 over the tunnel
  itself (`streaming/wired_session.py`), since `adb forward` can't carry
  WebRTC's UDP media — so it needs no Wi-Fi at all.
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
- For Android over USB: `android-tools` (provides `adb`) on the host, and
  USB debugging enabled on the device. The host then uses `adb forward`
  instead of `iproxy` (`transport/adb.py`). Wi-Fi needs neither.
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

**Android** (verified 2026-10-04 on a vivo Y28, Android 15): works over both
transports. Over Wi-Fi it uses the same WebRTC session as the iPad. Over USB
it uses the wired stream (`streaming/wired_session.py`): H.264 + control
messages straight through the `adb forward` tunnel, no Wi-Fi involved.

Not yet done: adaptive bitrate from `stats` messages, mDNS discovery for
Wi-Fi, Pencil pressure/hover, and Wayland support (phase 2).

## Running it

On an Xorg desktop with an iPad connected by cable:

```sh
# 1. Automatic: on start, the host forces a spare GPU connector "connected"
#    itself (passwordless sudo, else a graphical pkexec prompt). Only run the
#    script by hand if that fails or you want to pick the connector:
./host/scripts/force-connector.sh HDMI-A-1

#    Hotplugging a real monitor onto the forced port mid-session: set
#    VIEWDOCK_AUTO_HANDOFF=1 and the host moves the virtual display to
#    another output (experimental, see Troubleshooting).
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

`cvt` rounds widths to a multiple of 8, so 1180 becomes 1184 — `x11.py`
patches this back to the exact requested width internally, so the stream's
aspect ratio always matches the configured size exactly.

### Android sizing

Android devices have no fixed model list, so the presets are generic landscape
sizes: **Android phone (20:9) = 1440x648** (tested on a vivo Y28) and **Android
tablet (16:10) = 1280x800** (untested). For an exact fit, set
`VIEWDOCK_DISPLAY_WIDTH`/`HEIGHT` to the device's landscape size — but keep it
modest: a forced spare output has a pixel-clock ceiling (see Troubleshooting),
and a phone's native resolution is usually larger than useful on a desktop
anyway. The app is landscape-only.

### Optional: sharper native-pixel capture (`VIEWDOCK_DISPLAY_SCALE`)

By default the virtual display's actual XRandR mode is the iPad's logical
point size (see above) — correct UI size, but the iPad upscales 2x to fill
its retina panel, so text is softer than the panel is capable of. Setting
`VIEWDOCK_DISPLAY_SCALE=2` makes the actual mode/capture resolution the
iPad's full physical pixel size instead (e.g. 2360x1640), eliminating that
upscale.

This is **opt-in and narrow-purpose**: X11 has no per-output DPI, so nothing
about an existing window changes when you raise this — an app you **drag
over** from the built-in screen keeps rendering at whatever density it
started with, and will look small in the corner of the now-bigger virtual
canvas. The pairing that actually helps is an app you're launching **fresh**
specifically for the virtual display, via
`host/scripts/launch-on-virtual-display.sh <scale> <command>`, which sets
`QT_SCALE_FACTOR`/`GDK_SCALE` so that app renders at matching density:

```sh
VIEWDOCK_DISPLAY_SCALE=2 python -m host.main
# in another terminal, once the virtual display exists:
./host/scripts/launch-on-virtual-display.sh 2 kate
# then drag the new window onto the virtual display as usual
```

Leave this at the default (unset, i.e. 1) unless you specifically want that
workflow — it doesn't improve anything for the normal drag-a-window-over
usage this project is built around.

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

## Stream quality tuning

The video is H.264 (software x264), tuned in `streaming/encoder_tuning.py`.
aiortc's stock encoder is meant for webcam calls (0.5-3 Mbps, default
preset), which is too tight for a desktop full of text. Bitrate adapts
automatically between a floor and ceiling, driven by RTT and packet loss
from the host's own RTCP reports (`streaming/bitrate_controller.py`): it
backs off quickly on loss/delay and probes upward slowly when clean. While
streaming, a `pipeline:` line is logged every 5s with fps, capture/convert/
encode time (avg/p95), RTT, loss, and the current target bitrate.

| Variable | Default | Meaning |
|---|---|---|
| `VIEWDOCK_INITIAL_BITRATE_MBPS` | `6.0` | Starting bitrate |
| `VIEWDOCK_MIN_BITRATE_MBPS` / `VIEWDOCK_MAX_BITRATE_MBPS` | `1.0` / `10.0` | Adaptation range |
| `VIEWDOCK_X264_PRESET` | `veryfast` | x264 preset (`ultrafast` = least CPU) |
| `VIEWDOCK_TARGET_FPS` | `30` | Stream frame rate |
| `VIEWDOCK_KEYFRAME_INTERVAL` | `30.0` | Seconds between keyframes |
| `VIEWDOCK_VIDEO_CODEC` | `h264` | `vp8` to offer VP8 first instead |
| `VIEWDOCK_WIRED_BITRATE_MBPS` | `20.0` | Fixed bitrate of the Android USB stream (not adaptive; a cable has the bandwidth) |
| `VIEWDOCK_WIRED_KEYFRAME_INTERVAL` | `10.0` | Seconds between keyframes on the Android USB stream (the phone can also ask for one) |

The first four rows above (bitrate range, preset, FPS, keyframe interval) are
WebRTC settings; the Android USB stream uses `VIEWDOCK_X264_PRESET` and
`VIEWDOCK_TARGET_FPS` but has its own bitrate and keyframe settings.

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
  XFixes is unavailable; check host output. A single failed cursor query
  (seen: an XFixes `BadAccess` right after rearranging displays) only skips
  the cursor for that frame and logs one "skipping it this frame" warning;
  the overlay is only disabled after ~2 s of consecutive failures.
- **`Failed to open the uinput device: No such device` (Errno 19) on
  connect.** `/dev/uinput` exists but the `uinput` kernel module isn't
  loaded, so opening it fails. Load it now and on every boot:
  ```sh
  sudo modprobe uinput
  echo uinput | sudo tee /etc/modules-load.d/uinput.conf
  ```
- **`iproxy: ... Address already in use` for port 8766.** An `iproxy` from
  an earlier run that crashed or was `kill`ed is still holding the port.
  `pkill -x iproxy`, then start the host again.
- **iPad connects but shows no display (black), with a real monitor
  plugged in.** The real monitor took the connector you usually force
  (e.g. `HDMI-A-1`), so the host picked a different spare output, one
  that was never forced at the DRM level and that KDE therefore won't
  treat as a screen. `xrandr | grep connected` shows it as `disconnected`
  but with a `viewdock_*` geometry. Stop the host with Ctrl+C, force that
  connector instead (e.g. `./host/scripts/force-connector.sh DP-1`; the
  DRM name is listed under `/sys/class/drm/card*-*`), and restart.
- **USB stays on "waiting for iPad" after plugging in.** Normal if the app
  isn't open yet — a device shows up as USB-paired well before anything is
  listening on the tunneled port, and the host now retries patiently and
  indefinitely for exactly this gap rather than giving up after a few
  seconds. Open (or foreground) the app and grant Local Network permission
  (Settings > Privacy & Security > Local Network) if it still doesn't
  connect. Note that older builds of the app stop listening after a single
  failed connection attempt and need a relaunch; see TODO/TODO.md.
- **A real monitor plugged into the forced connector shows "No signal".**
  If you're reusing the same physical port for the iPad's virtual display
  and an actual monitor at different times, a connector left forced "on"
  from an earlier view-dock session overrides the cable's own hotplug/EDID
  detection — `xrandr` may still claim it's "connected" with a real-looking
  mode list (stale cached EDID), but the GPU isn't actually driving output
  to it. Reset the force state before plugging in a real monitor:
  ```sh
  echo unspecified | sudo tee /sys/kernel/debug/dri/*/HDMI-A-1/force
  ```
  **Not** `./host/scripts/force-connector.sh HDMI-A-1 off` — `off` is a
  *different* force state (permanently forced disconnected), not "no
  force"; it won't fix this either. `unspecified` is what actually restores
  normal kernel auto-detection.
- **"Configure crtc N failed" with a real monitor plugged into a different
  output.** Two possible causes, in order of likelihood:
  1. The spare output the host picked for the virtual display (check the
     error: `xrandr --output <name> ...`) has never been force-connected —
     `force-connector.sh` only forces whichever connector you've told it
     to, and a different one can end up as the "spare" once a real monitor
     occupies the one you usually force. Force that one too (same steps as
     "Real GPU output on an Xorg desktop" above, substituting the new
     connector name).
  2. Even force-connected, the mode itself might be too bandwidth-heavy for
     a third simultaneous output on some iGPUs — confirmed live on an Intel
     Iris Xe (Tiger Lake): plain `cvt`'s ~79MHz-pixel-clock mode for
     1180x820@60 failed as a third output even though that same GPU had
     driven 3-4 *real* monitors simultaneously before (so it wasn't a
     simultaneous-output-count limit), while a reduced-blanking ~68MHz
     equivalent worked. `displayserver/x11.py` already uses `cvt -r` for
     exactly this reason — if you're hitting this on a build older than
     that fix, update; if it still happens, your spare output's actual
     available bandwidth with your other active displays may be lower
     still, worth testing a lower `VIEWDOCK_DISPLAY_WIDTH`/`HEIGHT` or
     `VIEWDOCK_DISPLAY_REFRESH_HZ`.

- **"No spare output" / no outputs other than the built-in screen listed by
  `xrandr`.** Check `echo $XDG_SESSION_TYPE`: on a **Wayland** session
  `xrandr` only sees XWayland and none of the real connectors, so the host
  can't create the display (forcing a connector won't help). Log out and
  pick the **Plasma (X11)** session at the login screen.
- **`xrandr ... Configure crtc N failed` when enabling the display.** The
  mode's pixel clock is too high for the output. A forced **DisplayPort**
  output with nothing plugged in has a lower ceiling than HDMI — seen live
  on a DP output: 71 MHz worked, 78 MHz (1600x720) failed. Use a smaller
  size (the Android phone preset is 1440x648 for this reason) or force an
  HDMI output instead (`./host/scripts/force-connector.sh HDMI-A-1`). The host
  now reports this with a message instead of a traceback and cleans up the
  half-created mode.
- **Android: host stays on "waiting for device".** `adb devices` must list the
  phone as `device` — `unauthorized` means the "Allow USB debugging?" prompt
  on the phone hasn't been accepted, and no device at all usually means the
  cable is charge-only or USB debugging is off. Then open the app; it listens
  for the host.
- **Android over Wi-Fi never connects.** The phone must be able to reach the
  host's port 8765. Test with a TCP connect from the phone; some routers
  isolate Wi-Fi clients from each other ("AP/client isolation"), in which
  case use USB instead.

## Tests

```sh
python -m pytest host/tests/
```
