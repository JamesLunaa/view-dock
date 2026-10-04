# view-dock

view-dock turns an iPad or an Android phone/tablet into a real secondary
display for an Arch Linux machine — not a mirror, an actual extended desktop
you can drag windows onto — over Wi-Fi (same network) or a wired USB cable. A
Python host app on Arch creates a virtual display, captures and streams it; a
native iPadOS app or Android app renders the stream full-screen and forwards
touch (and Apple Pencil / stylus) input back to the host. Both apps speak the
same protocol.

## Status

Working end-to-end as a real extended display: windows drag from the
built-in screen onto the iPad or Android device and render there live, with
the mouse cursor visible, at correct UI scale. Both Wi-Fi and USB work, with
USB preferred automatically when a cable is plugged in, and the session
reconnects on its own after a dropped connection instead of needing to be
restarted.

**Android is supported** (phones and tablets, Android 8.0+), tested on one
device so far — see [Compatibility](#compatibility). Over USB it needs no
Wi-Fi at all: video and input travel through the cable itself, so it also
works on a network where devices can't reach each other.

**Known limitations**, tracked for future work:
- Touch input is forwarded and injected, but moves the host's *shared*
  pointer rather than acting as a touchscreen bound to the virtual display's
  region.
- No Apple Pencil / stylus pressure or hover — the host injects position and
  contact only (the Android app does send stylus pressure; the host ignores
  it for now).
- No Wi-Fi discovery yet (the host's IP is typed into the app by hand).
- Wayland is not supported on the host yet (X11 only).
- Android: landscape only. Keep the app in the foreground — while it is in the
  background the picture pauses, and it is meant to resume (via a fresh
  keyframe) when you return, but that hasn't been tested. Android apps are
  built from source; there is no Play Store or prebuilt release yet.
- The iPad's USB connection carries only the connection handshake; its video
  still travels over Wi-Fi. (Android's USB connection carries everything.)
- Neither transport authenticates the device to the host — see
  [Security](#security) before running this on a network you don't control.

## Security

view-dock streams your desktop and lets the remote end click on it, so it's
worth being explicit about what that currently does and doesn't protect.
[SECURITY.md](SECURITY.md) has the full model and the reporting process;
the short version:

**Encrypted: yes on every network path.** Over Wi-Fi (and for the iPad),
video and the control data channel ride a standard WebRTC session — SRTP for
media, DTLS-keyed SCTP for data. That is mandatory in WebRTC and there is no
plaintext fallback, so nobody passively sniffing your network can read your
screen off the wire. The one exception is **Android over USB**: that stream
isn't WebRTC and isn't encrypted, but it never touches the network — it
travels inside the USB cable through an `adb` tunnel to a listener bound to
the phone's loopback address only.

**Authenticated: no, not at all.** There is no pairing step, no token, and
no password. The signaling handshake that sets the session up is plain
`ws://` with no TLS, and the host accepts the first client that completes
it. Over Wi-Fi the host listens on `0.0.0.0:8765`, so on a network with a
hostile device present, that device could connect ahead of your iPad and
get a live view of the extended display plus the ability to move and click
the host's pointer. (It could not type: the virtual input device exposes
pointer motion and a touch button only, and every message is schema
validated before it's acted on.) Because the DTLS fingerprints are exchanged
over that same unauthenticated channel, encryption also doesn't stop an
attacker who can actively rewrite signaling traffic.

In practice: run it on a network you trust, prefer the USB cable (for
Android that means no network exposure at all), and firewall port 8765 if
you're somewhere you'd rather not assume that.
Authentication is a known gap and is tracked in SECURITY.md, not a disputed
report.

## Compatibility

This is a two-machine project; both sides have their own tested
configuration. "Tested" below means verified working on real hardware, not
just expected to work — other configurations in the same ballpark are
likely fine but haven't been confirmed.

| | Tested configuration | Notes |
|---|---|---|
| **Host** | Arch Linux, KDE Plasma, **Xorg** (X11) session | The virtual-display approach relies on forcing a GPU connector "on" at the kernel/DRM level so KDE's `kscreen` treats it as a real monitor — see `host/README.md`'s "Real GPU output on an Xorg desktop" for why, and why Wayland doesn't work the same way yet. Other X11 window managers/desktop environments likely work for the core display pipeline, but the kscreen-specific connector-forcing step is KDE-specific and untested elsewhere. |
| **iPad** | iPad Air 11" (M3), iPadOS 26.6 | The Xcode project's deployment target is iOS 17.0, so earlier iPadOS versions and other iPad models should work in principle, but only this specific device/OS combination has actually been run. |
| **Android** | vivo Y28 (V2352), Funtouch OS 15 (Android 15), phone — USB and Wi-Fi both verified | `minSdk` is 26 (Android 8.0), so other versions and devices, including tablets, should work in principle, but only this device has actually been run. The host's "Android tablet" size preset is a guess, untested. |
| **Mac** (to build the iPad app only) | Any recent Xcode with the iOS 17 SDK | No specific Xcode version is pinned; building requires [XcodeGen](https://github.com/yonaskolb/XcodeGen) and a free or paid Apple Developer account to code-sign onto a physical device (the iPad app hasn't been run in the Simulator — WebRTC/video needs real hardware). |

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
- For Android over USB: `android-tools` (provides `adb`), and USB debugging
  enabled on the device. Not needed for Wi-Fi.
- The `uinput` kernel module loaded (`sudo modprobe uinput`) for touch/Pencil
  input injection — this does not persist across reboots.
- Optional: PySide6 (`pip install PySide6`), only needed for the tray
  applet/window GUI (`host/gui/`) — the terminal UI and CLI need nothing
  beyond the core Python dependencies.

**iPad:**
- iPadOS 17.0 or later (tested on iPadOS 26.6). The app is iPad-only (no
  iPhone) and supports any iPad that can run iPadOS 17, i.e.:
  - iPad (6th generation, 2018) and newer
  - iPad mini (5th generation) and newer
  - iPad Air (3rd generation) and newer
  - iPad Pro 10.5", 11" (all generations) and 12.9" (2nd generation) and newer

  Older models (iPad 5th gen and earlier, iPad mini 4 and earlier, iPad Air 2
  and earlier, the first-generation iPad Pro) can't run iPadOS 17 and are not
  supported. Only the iPad Air 11" (M3) has actually been tested; other
  supported models should work but are unconfirmed, and older chips (A10/A11)
  may struggle with high-resolution, high-refresh-rate streams. Both
  Lightning and USB-C iPads work for the wired transport.
- The view-dock app installed via Xcode (see Installation below) — it isn't
  distributed through the App Store.

**Android:**
- Android 8.0 (API 26) or later, phone or tablet. Tested on Android 15 (see
  Compatibility above).
- For USB: *Settings → Developer options → USB debugging* switched on, and
  the "Allow USB debugging?" prompt accepted for your computer. For Wi-Fi:
  the device and the host on the same network, with a router that lets
  devices talk to each other (some guest networks and "AP isolation" modes
  don't).
- The app installed by sideloading (see Installation below) — it isn't
  distributed through the Play Store.

**Building the Android app** (any machine; no Mac needed): JDK 17 or later and
the Android SDK (platform 37 and build-tools). See `android/README.md`.

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

(For an exact, hash-verified dependency set instead of the floating version
ranges — the same one CI installs — use
`pip install --require-hashes -r host/requirements.lock.txt`. See
[CONTRIBUTING.md](CONTRIBUTING.md#reproducible-builds).)

#### Other distros (untested)

Only Arch has been verified on real hardware. Nothing in the host code is
Arch-specific, so other distros should work if they provide the same
prerequisites — these are the equivalent packages, but none of the rows below
have been run:

| Distro | Packages |
|---|---|
| Manjaro / EndeavourOS / CachyOS | Same as Arch above. |
| Debian / Ubuntu / Mint / Pop!_OS | `sudo apt install xserver-xorg-video-dummy x11-xserver-utils ffmpeg usbmuxd libimobiledevice-utils` |
| Fedora | `sudo dnf install xorg-x11-drv-dummy xrandr ffmpeg usbmuxd libimobiledevice-utils` (full codec support may need RPM Fusion) |
| openSUSE | `sudo zypper install xf86-video-dummy xrandr ffmpeg usbmuxd libimobiledevice-tools` |

Things to keep in mind on any distro:

- **Log in to an X11/Xorg session.** Wayland isn't supported yet, and several
  distros (Ubuntu, Fedora) now default to it.
- **Packaged `libimobiledevice` may be too old** to pair with iOS 17+/iPadOS 26+
  (see `host/README.md`); USB may need a newer build from source. Wi-Fi is
  unaffected.
- **The connector-forcing step is untested outside KDE Plasma.** Other desktops
  may or may not need it.
- For Android USB, install `adb` (Debian/Ubuntu: `adb`; Fedora/openSUSE:
  `android-tools`) — also untested there.
- Python 3.11+ and the `uinput` setup above apply everywhere.

Then follow `host/README.md`'s "Real GPU output on an Xorg desktop" section
once, to set up the virtual display's connector — it's the one step that
can't be fully automated (it writes to a kernel debugfs file under `sudo`),
and needs re-running after every reboot unless you add the suggested kernel
command-line option for a permanent fix.

### 2. App icon for the host GUI (optional, recommended)

By default, launching the host means opening a terminal every time. To get a
normal clickable app icon instead:

```sh
pip install PySide6          # if you skipped it above
./host/scripts/install-desktop-entry.sh
```

This drops a `.desktop` entry into `~/.local/share/applications`, so
"view-dock Host" shows up in your application menu/launcher like any other
installed app — clicking it runs `python -m host.gui` with the right working
directory, no terminal needed.

**One remaining catch:** the virtual display's connector only stays forced
until reboot (see "Real GPU output on an Xorg desktop" in step 1), so by
default you still need to run `./host/scripts/force-connector.sh` from a
terminal once per boot before the icon will work — the GUI will tell you
to do this (with a suggested connector name) if you click the icon without
it. To make the icon fully standalone — no terminal, ever — add the kernel
command-line option mentioned in that same section
(`video=HDMI-A-1:e`, substituting your connector) so the connector is
force-connected automatically at every boot. Once that's in place, the app
icon is the entire host-side workflow: click it, start the session from the
window that opens, done.

### 3. iPad app setup (on a Mac)

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
3. Turn on **Developer Mode** on the iPad (iPadOS 16 and later): plug it into
   the Mac with Xcode open, then go to Settings → Privacy & Security →
   Developer Mode, switch it on, and restart when prompted. The toggle only
   appears once the iPad has been connected to Xcode.
4. Select your iPad as the run destination and Build & Run (`⌘R`). The first
   launch will ask you to trust the developer certificate on the iPad
   (Settings → General → VPN & Device Management).

### 4. Android app setup (optional, instead of or alongside the iPad)

Any machine with a JDK and the Android SDK can build it — see
`android/README.md` for the one-time setup:

```sh
cd view-dock/android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

(Or copy `app-debug.apk` to the device and open it; you'll need to allow
installs from that source.) There's no signing key or developer account
involved for a debug build.

### 5. First connection

With the host's virtual display set up (step 1) and the app installed on
your iPad (step 3) or Android device (step 4):

1. On the host, launch it one of three ways (see `host/README.md`'s
   "Running it" for the full picture):
   - **GUI** (recommended for daily use): click the "view-dock Host" app
     icon from step 2, or run `python -m host.gui` directly.
   - **Terminal UI**: `python -m host.ui` — no extra dependency, works over
     SSH.
   - **Raw CLI**: `python -m host.main` — for scripting/debugging.
2. Pick a display size that matches the device — the host's GUI/TUI list has
   presets for iPads and for an Android phone (20:9) or tablet (16:10); see
   `host/README.md`'s "Sizing" section.
3. Open the view-dock app. Plug the device in by cable for USB (lower
   latency, auto-preferred when connected; on Android, USB debugging must be
   on), or enter the host's IP address in the app for Wi-Fi.
4. It should connect within a few seconds. Drag a window from your main
   screen onto the new extended-display area to confirm it's working.

If something doesn't connect, `host/README.md`'s Troubleshooting section
covers the issues most likely to come up (missing permissions, a stale
virtual display mode, the DRM connector step needing a re-run after reboot).

## Project layout

- `host/` — the Python server: virtual display creation, capture, WebRTC
  and wired streaming, input injection, and three ways to run it (GUI, terminal UI,
  CLI). See `host/README.md` for full detail.
- `ipad/` — the native iPadOS app (SwiftUI + WebRTC). See `ipad/README.md`.
- `android/` — the native Android app (Kotlin + Jetpack Compose). See
  `android/README.md`.
- `protocol/` — the wire protocol shared by all sides: handshake, display
  metadata, input events, and the wired stream used over Android USB. See
  `protocol/PROTOCOL.md`. Changes here are cross-cutting — `host/`, `ipad/`
  and `android/` all need updating together.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, how the test suite is
structured, the protocol-change checklist, and release/build details.
Security issues go through [SECURITY.md](SECURITY.md) instead of the public
issue tracker. Notable changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)
