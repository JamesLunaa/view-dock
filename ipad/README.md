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

This resolves the WebRTC Swift package dependency and produces a normal
Xcode project you can build and run on a physical iPad (WebRTC and camera/
screen APIs generally don't work in the Simulator for this kind of app).

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

**Wired stream over USB (new):** implemented and unit-tested, but **not yet
run on a real iPad** — treat the first build as untested. With it, the USB
cable carries the video and input itself, so the iPad works with no shared
Wi-Fi (previously the cable carried only the handshake and the video still
took Wi-Fi). On connect the app sends a `hello` announcing support; a host
at protocol 1.2 or later answers and streams H.264 through the tunnel, which
`AVSampleBufferDisplayLayer` decodes in hardware. Against an older host the
app is not compatible over USB (keep host and app at the same version); an
older *app* against a newer host simply keeps using WebRTC. What was tested
without an iPad is listed under "Tests" below; everything that touches
AVFoundation, CoreMedia, Network or SwiftUI could only be syntax-checked on
Linux and is the part to watch on the first build.

Not yet done: Wi-Fi discovery (host IP is typed in manually — no mDNS yet) and
Pencil-specific input (pressure/hover; only plain touch is forwarded today).

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
