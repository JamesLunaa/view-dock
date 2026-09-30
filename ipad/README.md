# ipad

Native iPadOS app (SwiftUI). Renders the WebRTC video stream from `host/`
full-screen and forwards touch/Pencil input back over the `control` data
channel, per `protocol/PROTOCOL.md`.

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
  host, mirroring `host/transport/`), `WebRTCClient` (peer connection, video
  track rendering, control data channel).
- `Sources/Protocol/Messages.swift` — Swift mirror of
  `protocol/messages.py` / `protocol/schema/*.json`. Keep in sync by hand
  when the protocol changes.
- `Sources/Input/TouchInputForwarder.swift` — captures touch/Pencil events
  from the video view and sends them as `input_event` messages.
- `Resources/Info.plist` properties (local network + Bonjour usage) are
  defined in `project.yml`; XcodeGen writes the actual plist.

## Status

Implemented: SDP offer/answer negotiation over a bootstrap signaling channel
(`Networking/SignalingChannel.swift`), full-screen video rendering
(`Networking/RemoteVideoView.swift`, Metal-backed), and touch input
forwarding over the `control` data channel. For Wi-Fi the iPad connects out
to the host's signaling server (`WifiSignaling`, `URLSessionWebSocketTask`);
for USB the iPad is instead the listener (`UsbSignaling` +
`WebSocketServer.swift`, a minimal RFC 6455 server), since `iproxy` on the
host relays through to a port only the device can be listening on — see
`host/transport/usb.py`.

Not yet done: Wi-Fi discovery (host IP is typed in manually — no mDNS yet),
Pencil-specific input (pressure/hover; only plain touch is forwarded today),
and reconnect handling. None of this has been built with Xcode yet — it's
only been reviewed for correctness on Linux (no Swift toolchain available
here), so build errors on first `xcodegen generate` + build are likely and
expected.
