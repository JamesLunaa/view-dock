# ipad

Native iPadOS app (SwiftUI). Renders the video stream from `host/`
full-screen and forwards touch/Pencil input back, per `protocol/PROTOCOL.md`.
Over Wi-Fi the video is a WebRTC stream; over a USB cable it is a plain H.264
stream through the cable itself (the "wired stream" — no Wi-Fi needed).

## Generating the Xcode project

This repo is developed partly on Linux, where Xcode isn't available, so the
`.xcodeproj` isn't checked in — it's generated from `project.yml` via
[XcodeGen](https://github.com/yonaskolb/XcodeGen). On a Mac, with XcodeGen
installed (`brew install xcodegen`):

```sh
cd ipad
xcodegen generate
open ViewDock.xcodeproj
```

Re-run `xcodegen generate` after pulling changes: new source files and the app icon only
reach the project when it is regenerated. (If the icon doesn't update on the iPad, delete the
app before reinstalling — iOS can keep showing the old one.)

This resolves the WebRTC Swift package dependency and produces a normal
Xcode project you can build and run on a physical iPad (WebRTC and camera/
screen APIs generally don't work in the Simulator for this kind of app).

## Building on Linux with xtool

[xtool](https://xtool.sh) builds the app with SwiftPM, signs it with your Apple ID and
installs it over USB, without a Mac. `xtool/` holds its config: `Package.swift` (the app is
the package's single library product, with the WebRTC dependency), `xtool.yml`,
`Info.plist` (the same keys as `project.yml`'s `info` section; keep the two in step), and
`Sources/ViewDock`, a symlink to `ipad/Sources` because SwiftPM won't take a target path
outside the package. Both builds compile the same sources.

One-time setup:
1. Install the [Swift 6.4 toolchain](https://swift.org/install/linux), `usbmuxd`, and the
   xtool AppImage from its
   [releases](https://github.com/xtool-org/xtool/releases/latest) (rename it `xtool` and
   put it on your `PATH`).
2. Download Xcode from <https://developer.apple.com/download/all/?q=Xcode> in a browser
   (it needs an Apple login). xtool takes the iOS SDK from the `.xip`.
3. Run `xtool setup`. Log in with your Apple ID (or an App Store Connect API key with a
   paid account), then give it the path to the `.xip`.
4. On the iPad, turn on Developer Mode (Settings → Privacy & Security).

Then, with the iPad plugged in and unlocked:

```sh
cd ipad/xtool
xtool dev
```

The first launch asks you to trust the developer (Settings → General → VPN & Device
Management). With a free Apple ID the app stops opening after 7 days; run `xtool dev` again
to reinstall.

**Arch Linux:** Swift's Linux toolchain is built for Ubuntu and looks for `libxml2.so.2` and
`libncurses.so.6`, which Arch names differently. Symlink them into the toolchain (paths
relative to the toolchain's `usr/`):

```sh
ln -s /usr/lib/libxml2.so.16 lib/swift/linux/libxml2.so.2
ln -s /usr/lib/libncursesw.so.6 lib/swift/linux/libncurses.so.6
ln -s /usr/lib/libxml2.so.16 lib/libxml2.so.2   # for the linker, lld
```

Without the last one the build fails with `Could not parse output of ... ld.lld
-version_details as JSON`. The build also caches that failure, so delete `xtool/.build/out`
after adding the link.

## Layout

- `Sources/ViewDockApp.swift` — SwiftUI app entry point.
- `Sources/ContentView.swift` — full-screen video view + connection status UI.
- `Sources/Networking/` — `ConnectionManager` (picks Wi-Fi vs. USB-cabled
  host, mirroring `host/transport/`), `WebRTCClient` (Wi-Fi: peer connection,
  video track rendering, control data channel), and for the USB wired stream
  `WiredClient` (reads the tunnel, hands frames to an
  `AVSampleBufferDisplayLayer`), `H264SampleBufferFactory` (Annex-B →
  `CMSampleBuffer`), `WiredVideoView`, plus the Foundation-only
  `WebSocketFraming` and `H264AnnexB` that those build on.
- `Package.swift` + `Tests/` — a SwiftPM package that exists only to unit-test the
  Foundation-only logic with `swift test` (see Tests below); it is not how the app is built.
- `xtool/` — the build config for xtool on Linux (see above).
- `Resources/Assets.xcassets` — the app icon, generated from
  `branding/icon.svg` (see `CONTRIBUTING.md`); don't edit the PNG by hand.
- `Sources/Protocol/Messages.swift` — Swift mirror of
  `protocol/messages.py` / `protocol/schema/*.json`. Keep in sync by hand
  when the protocol changes.
- `Sources/Input/TouchInputForwarder.swift` — captures touch/Pencil events
  from the video view and sends them as `input_event` messages.
- `Resources/Info.plist` properties (local network + Bonjour usage) are
  defined in `project.yml`; XcodeGen writes the actual plist.

## Status

**Wi-Fi / WebRTC path:** working on an iPad Air 11" (M3) — see the top-level
README's Compatibility table. SDP offer/answer negotiation over a bootstrap
signaling channel (`Networking/SignalingChannel.swift`), full-screen video
(`Networking/RemoteVideoView.swift`, Metal-backed), touch input over the
`control` data channel. For Wi-Fi the iPad connects out to the host's
signaling server (`WifiSignaling`); for USB the iPad is the listener
(`UsbSignaling` + `WebSocketServer.swift`, a minimal RFC 6455 server), since
`iproxy` on the host relays through to a port only the device can be listening
on — see `host/transport/usb.py`.

**Wired stream over USB:** working — verified on an iPad Air 11" (M3), at 60 fps with the
host's default settings. The USB cable now carries the video and input itself, so the
stream doesn't use Wi-Fi at all (before, the cable carried only the handshake and the video
still took Wi-Fi). How it works: on connect the app sends a `hello` announcing support; a
host at protocol 1.2 or later answers and streams H.264 through the tunnel, which
`AVSampleBufferDisplayLayer` decodes in hardware. Against an older host the app is not
compatible over USB (keep host and app at the same version); an older *app* against a newer
host simply keeps using WebRTC.

What changed in the app for it:
- `Networking/WiredClient.swift` reads the tunnel and feeds an `AVSampleBufferDisplayLayer`;
  `H264SampleBufferFactory` turns the host's Annex-B access units into `CMSampleBuffer`s;
  `WiredVideoView` hosts the layer in SwiftUI.
- `WebSocketServer.swift` now understands binary frames, pings and fragmented messages (it
  used to accept text frames only), with the framing logic split out into
  `WebSocketFraming.swift` so it can be unit-tested.
- `Protocol/Messages.swift` gained the `keyframe_request` message, the wired video-frame
  header and protocol version 1.2.
- In the wired view the video is sized to the host display's aspect ratio, so a touch inside
  it maps 1:1 onto the host display. (The Wi-Fi/WebRTC view still maps touches to the whole
  screen, which only matters when the stream's shape differs from the iPad's.)
- The app now has an icon (`Resources/Assets.xcassets`, generated from `branding/icon.svg`).

**Verified:** unplugging and replugging the cable mid-session reconnects. **Not yet re-checked
since the wired stream was added:** Wi-Fi-only mode and the app being sent to the background.

Wi-Fi discovery (Bonjour via `NWBrowser`; the first launch asks for Local Network access) is
implemented but untested on a device — the typed-IP field remains as a fallback. Not yet done:
Pencil-specific input (pressure/hover; only plain touch is forwarded today).

## About and Licenses

The connect screen has an **info (ⓘ)** button (top right) that opens an About sheet: the
app's version and copyright (James Luna), the GPL notices, the full GNU GPL v3 text, the
licenses of the libraries inside the app, and a link to the source code
(`Sources/Legal/`). The texts are bundled from `Resources/Legal/` — a folder reference in
`project.yml` — and are **generated**: edit `legal/components.json` and run
`python scripts/generate_legal.py`, don't change them by hand. The Foundation-only parts
(`AppInfo.swift`) are unit-tested; the SwiftUI screens (`AboutView.swift`) have not yet been
run on a device.

## Tests

The Foundation-only logic — protocol messages, WebSocket framing and H.264
Annex-B parsing — is covered by unit tests that run without Xcode, a simulator
or a device, on macOS or Linux:

```sh
cd ipad
swift test
```

They include frames serialized by the host's own libraries (Python's
`websockets` client frames and a real libx264 keyframe), so a framing or
bitstream mismatch with the host shows up here. The rest of the app needs
Apple frameworks and is only exercised by building and running it.
