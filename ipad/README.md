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

Scaffolding only — types and file boundaries are in place; WebRTC wiring,
video rendering, and input capture are not implemented yet.
