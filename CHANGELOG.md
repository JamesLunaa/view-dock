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

### Known limitations
- Touch moves the host's shared pointer rather than acting as a touchscreen
  bound to the virtual display's region.
- No Apple Pencil pressure or hover.
- No Wi-Fi discovery — the host's IP is typed into the app by hand.
- X11 only; no Wayland support on the host.
- No authentication or pairing on either transport — see
  [SECURITY.md](SECURITY.md).

[Unreleased]: https://github.com/JamesLunaa/view-dock/commits/master
