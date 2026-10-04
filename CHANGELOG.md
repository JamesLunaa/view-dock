# Changelog

Notable changes to view-dock. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once releases
start.

Because `protocol/` is the contract between two separately installed pieces
(the Arch host and the iPad app), entries that change it are called out
explicitly — a host and an app from different releases are only guaranteed
to interoperate if no protocol change sits between them.

## [Unreleased]

Nothing has been tagged yet; everything below is what currently lives on
`master`, and will become the first release (`0.1.0`).

### Added
- **Android support.** Android client (`android/`, Kotlin + Jetpack Compose)
  for phones and tablets, with touch and stylus input, over Wi-Fi or USB.
  Verified on a vivo Y28 (Android 15) over both transports. On the host,
  `transport/adb.py` tunnels USB via `adb forward` and is auto-detected
  alongside the iPad's usbmuxd transport. Over USB the Android client gets
  its video directly through the cable (a wired H.264 stream), so it works
  with no shared Wi-Fi. **Protocol changes (1.1, 1.2; both additive):**
  `hello.role` gains `android`; a wired stream (binary video frames on the
  signaling connection) and a `keyframe_request` message are added. A 1.0
  host drops messages it doesn't know, with a logged warning.
- Extended display over X11: a virtual monitor created via `xrandr`,
  captured with `mss`, with the cursor composited in separately via XFixes.
- WebRTC streaming of that display to a native iPadOS app (SwiftUI + the
  WebRTC framework), with touch/Pencil input forwarded back over the
  `control` data channel and injected on the host through `uinput`.
- Two transports behind one protocol: Wi-Fi (host runs the signaling
  server) and wired USB over `usbmuxd`/`iproxy` (the iPad runs it). USB is
  auto-detected and preferred when a cable is connected.
- Automatic reconnection after a dropped session, without restarting the
  host.
- Three ways to run the host: a PySide6 tray applet/window (`host.gui`), a
  terminal UI (`host.ui`), and a raw CLI (`host.main`), plus a `.desktop`
  entry installer so the GUI launches like a normal app.
- Display scaling and resolution presets, and a geometry watcher that keeps
  the session sane when other monitors are plugged in or out.
- JSON Schema definitions for every protocol message in `protocol/schema/`,
  validated at runtime on the host.
- Host test suite (`host/tests`, hardware mocked out) running in CI on every
  push and pull request.
- `host/requirements.lock.txt`: exact, hash-verified dependency pins for
  reproducible installs; CI installs from it.
- Security policy ([SECURITY.md](SECURITY.md)), including an explicit
  statement of what the WebRTC session does and does not protect.
- Dependency and code scanning through GitHub (Dependabot updates, CodeQL,
  dependency review on pull requests).

- **iPad wired stream (untested on hardware).** The iPad app can now take the
  same wired H.264 stream as Android over its USB cable, with no Wi-Fi: the
  app announces support with a `hello`, the host (protocol 1.2+) detects it and
  streams through the tunnel, and `AVSampleBufferDisplayLayer` decodes it. Older
  iPad builds keep using WebRTC. Unit tests for the Swift protocol, WebSocket
  framing and H.264 parsing run with `swift test` (macOS or Linux).

- App icons: the iPad app now has one (it had none), and the host icon is
  redrawn, all derived from a single master (`branding/icon.svg`, the Android
  icon's design) so the three platforms match. The host's tray icon, which used
  to be a bare status dot, now shows that icon with a status badge.

### Fixed
- The host no longer ends the whole session (and tears down the virtual
  display) when a device closes the signaling connection mid-handshake; it
  waits for the device to reconnect.
- When `xrandr` can't enable the virtual display's mode (for example a pixel
  clock too high for a forced DisplayPort output) the host now cleans up the
  half-created mode and says what to try, instead of crashing with a bare
  traceback.
- Android display-size presets no longer trigger the "unusual aspect ratio"
  warning meant for typos.

### Known limitations
- Touch moves the host's shared pointer rather than acting as a touchscreen
  bound to the virtual display's region.
- No Apple Pencil / stylus pressure or hover (the host injects position and
  contact only).
- Android apps are built from source (debug builds); the app is landscape-only
  and tested on a single device.
- The iPad's new wired USB stream has not been run on a real iPad yet; until
  then assume its video still needs Wi-Fi. Android's USB connection carries
  everything and is verified.
- No Wi-Fi discovery — the host's IP is typed into the app by hand.
- X11 only; no Wayland support on the host.
- No authentication or pairing on either transport — see
  [SECURITY.md](SECURITY.md).

[Unreleased]: https://github.com/JamesLunaa/view-dock/commits/master
