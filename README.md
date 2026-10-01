# view-dock

view-dock turns an iPad into a real secondary display for an Arch Linux
machine — not a mirror, an actual extended desktop you can drag windows onto
— over Wi-Fi (same network) or a wired USB cable. A Python host app on Arch
creates a virtual display, captures and streams it over WebRTC; a native
iPadOS app renders the stream full-screen and forwards touch/Pencil input
back to the host.

## Status

Working end-to-end as a real extended display: windows drag from the
built-in screen onto the iPad and render there live, with the mouse cursor
visible, at correct UI scale. Both Wi-Fi and USB work, with USB preferred
automatically when a cable is plugged in, and the session now reconnects on
its own after a dropped connection instead of needing to be restarted.

**Known limitations**, tracked for future work:
- Touch input is forwarded and injected, but moves the host's *shared*
  pointer rather than acting as a touchscreen bound to the virtual display's
  region.
- No Apple Pencil pressure/hover — plain touch only.
- No Wi-Fi discovery yet (the host's IP is typed into the app by hand).
- Wayland is not supported on the host yet (X11 only).

## Compatibility

This is a two-machine project; both sides have their own tested
configuration. "Tested" below means verified working on real hardware, not
just expected to work — other configurations in the same ballpark are
likely fine but haven't been confirmed.

| | Tested configuration | Notes |
|---|---|---|
| **Host** | Arch Linux, KDE Plasma, **Xorg** (X11) session | The virtual-display approach relies on forcing a GPU connector "on" at the kernel/DRM level so KDE's `kscreen` treats it as a real monitor — see `host/README.md`'s "Real GPU output on an Xorg desktop" for why, and why Wayland doesn't work the same way yet. Other X11 window managers/desktop environments likely work for the core display pipeline, but the kscreen-specific connector-forcing step is KDE-specific and untested elsewhere. |
| **iPad** | iPad Air 11" (M3), iPadOS 26.6 | The Xcode project's deployment target is iOS 17.0, so earlier iPadOS versions and other iPad models should work in principle, but only this specific device/OS combination has actually been run. |
| **Mac** (to build the iPad app) | Any recent Xcode with the iOS 17 SDK | No specific Xcode version is pinned; building requires [XcodeGen](https://github.com/yonaskolb/XcodeGen) and a free or paid Apple Developer account to code-sign onto a physical device (the iPad app hasn't been run in the Simulator — WebRTC/video needs real hardware). |

## Requirements

**Host (Arch Linux):**
- X11 session (KDE Plasma on Xorg is the tested desktop — see Compatibility
  above). Not Wayland yet.
- System packages: `xorg-server`, `xorg-xrandr`, `xf86-video-dummy`, `ffmpeg`.
- Python 3.11+.
- For USB: `usbmuxd` + `libimobiledevice`, specifically the AUR `-git`
  builds — see `host/README.md`'s Requirements section for why the official
  Arch packages don't work with recent iPadOS, and a known side effect of
  installing the `-git` ones.
- The `uinput` kernel module loaded (`sudo modprobe uinput`) for touch/Pencil
  input injection — this does not persist across reboots.
- Optional: PySide6 (`pip install PySide6`), only needed for the tray
  applet/window GUI (`host/gui/`) — the terminal UI and CLI need nothing
  beyond the core Python dependencies.

**iPad:**
- iPadOS 17.0 or later (tested on iPadOS 26.6).
- The view-dock app installed via Xcode (see Installation below) — it isn't
  distributed through the App Store.

**Mac, to build the iPad app:**
- Xcode, with [XcodeGen](https://github.com/yonaskolb/XcodeGen) installed
  (`brew install xcodegen`).
- A free or paid Apple Developer account, to code-sign the app for your
  physical iPad.

## Installation

### 1. Host setup (on the Arch Linux machine)

```sh
git clone https://github.com/JamesLunaa/view-dock.git
cd view-dock

# System packages
sudo pacman -S xorg-server xorg-xrandr xf86-video-dummy ffmpeg
yay -S usbmuxd-git libimobiledevice-git libusbmuxd-git libplist-git libimobiledevice-glue-git

# Python environment
python -m venv .venv
source .venv/bin/activate
pip install -r host/requirements.txt

# Load the uinput module now, and set it to load at every boot
sudo modprobe uinput
echo uinput | sudo tee /etc/modules-load.d/uinput.conf
```

Then follow `host/README.md`'s "Real GPU output on an Xorg desktop" section
once, to set up the virtual display's connector — it's the one step that
can't be fully automated (it writes to a kernel debugfs file under `sudo`),
and needs re-running after every reboot unless you add the suggested kernel
command-line option for a permanent fix.

### 2. iPad app setup (on a Mac)

```sh
git clone https://github.com/JamesLunaa/view-dock.git
cd view-dock/ipad
xcodegen generate
open ViewDock.xcodeproj
```

In Xcode:
1. Select the `ViewDock` project in the navigator, then the `ViewDock`
   target, then the **Signing & Capabilities** tab.
2. Under **Team**, choose your own Apple ID/team (add one via **Xcode →
   Settings → Accounts** first if you haven't signed in before). This fills
   in the `DEVELOPMENT_TEAM` that `project.yml` leaves blank — it's
   per-developer and can't be checked into the repo.
3. Plug your iPad in, select it as the run destination, and Build & Run
   (`⌘R`). The first launch will ask you to trust the developer certificate
   on the iPad (Settings → General → VPN & Device Management).

### 3. First connection

With the host's virtual display set up (step 1) and the app installed on
your iPad (step 2):

1. On the host, launch it one of three ways (see `host/README.md`'s
   "Running it" for the full picture):
   - **GUI** (recommended for daily use): `./host/scripts/install-desktop-entry.sh`
     once to add an app-launcher entry, then launch "view-dock Host" from
     your application menu — or run `python -m host.gui` directly.
   - **Terminal UI**: `python -m host.ui` — no extra dependency, works over
     SSH.
   - **Raw CLI**: `python -m host.main` — for scripting/debugging.
2. Open the view-dock app on the iPad. Plug it in by cable for USB (lower
   latency, auto-preferred when connected), or enter the host's IP address
   in the app for Wi-Fi.
3. It should connect within a few seconds. Drag a window from your main
   screen onto the new extended-display area to confirm it's working.

If something doesn't connect, `host/README.md`'s Troubleshooting section
covers the issues most likely to come up (missing permissions, a stale
virtual display mode, the DRM connector step needing a re-run after reboot).

## Project layout

- `host/` — the Python server: virtual display creation, capture, WebRTC
  streaming, input injection, and three ways to run it (GUI, terminal UI,
  CLI). See `host/README.md` for full detail.
- `ipad/` — the native iPadOS app (SwiftUI + WebRTC). See `ipad/README.md`.
- `protocol/` — the wire protocol shared by both sides: handshake, display
  metadata, input events. See `protocol/PROTOCOL.md`. Changes here are
  cross-cutting — both `host/` and `ipad/` need updating together.

## Contributing

Contributions, ideas, and feedback are welcome. If you're tackling one of
the known limitations above or something adjacent, opening an issue first
to compare notes is a good idea — some of these (touch-as-a-real-touchscreen
especially) have real design tradeoffs worth discussing before diving into
an implementation.

## License

[MIT](LICENSE)
