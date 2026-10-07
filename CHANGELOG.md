# Changelog

Notable changes to view-dock. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**How to read this file:** each `## [X.Y.Z] - date` heading is a release that has been
tagged, newest first. `## [Unreleased]` collects changes made since the latest tag.

## [Unreleased]

### Added
- **Several clients at once (host).** One host can now serve any mix of iPads and
  Android devices over Wi-Fi and USB at the same time. Each client gets its own
  virtual monitor (placed right of the previous one), capture, encoder and input
  device, up to `VIEWDOCK_MAX_CLIENTS` (default 4). A Wi-Fi client past the cap is sent
  a `bye` and disconnected; a USB device waits for a free slot. A client's monitor is
  kept for `VIEWDOCK_DISPLAY_LINGER_S` seconds (default 15) after it leaves so a
  reconnect gets it back. No `protocol/` change and no app change: existing apps work
  against this host unchanged. Each extra client needs its own spare GPU output.
  Unit-tested with fakes, and reported working with an iPad and an Android phone
  connected together over USB. Touch placement on the second monitor and three or more
  clients have not been checked.

### Changed
- The host no longer switches between Wi-Fi and USB mid-wait: it listens on both at
  once, and every attached USB device gets its own tunnel (per-device `iproxy -u` /
  `adb -s`).
- Expected display-layout hiccups (another client's monitor appearing) are logged as
  info instead of warnings with tracebacks, and the tray app only pops up notifications
  for errors, so normal connects no longer look alarming.
- A client that cannot get a virtual monitor (no spare output) is now refused with a
  `bye` while the rest keep streaming, instead of stopping the whole host.

## [2.0.4](https://github.com/JamesLunaa/view-dock/compare/v2.0.1...v2.0.2) - 2026-10-06

Minor fix: forced connector

## [2.0.3] - 2026-10-05

A fix-only release, so a patch: nothing added, no `protocol/` change, and any host and
app from 2.0.0 onward still interoperate. The `v2.0.3` tag was cut before this section
and the version strings (Android `versionName`, iPad `MARKETING_VERSION`,
`pyproject.toml`) were bumped, so they were updated in a follow-up commit; builds made
from the tag itself still report 2.0.2.

### Fixed
- **Plugging in a real monitor while streaming no longer breaks the session (X11).**
  The desktop could switch the virtual output off during the hotplug; the host kept
  capturing a rectangle that was no longer on the screen, every grab failed with an
  X `BadMatch` error, and each reconnect hit the same error in a loop until the client was
  unplugged. Capture failures now re-resolve the virtual output (up to 6 s), retry a
  failed geometry lookup until it succeeds, and re-enable the output if it was switched
  off. On KDE the host also asks `kscreen-doctor` to enable it (plain `xrandr` left
  Plasma not drawing on it, so the iPad showed black) and restores the previous primary
  display. Reported working on the user's machine (iPad over USB, real monitor plugged
  in mid-stream); no automated test covers this path.

## [2.0.2] - 2026-10-05

A packaging-only release: nothing changes at runtime, and any host and app from
2.0.0 onward still interoperate (no `protocol/` change). It is a patch release
because no feature was added; the host just became installable as a standard
Python package, which is what an Arch (AUR) package needs.

### Added
- **`pyproject.toml`.** The host can now be built and installed as a normal Python
  package (`python -m build`, `pip install .`). It provides the `view-dock`,
  `view-dock-tui` and `view-dock-tray` commands and bundles the protocol schemas and
  the tray icon. Dependencies mirror `host/requirements.txt`. Verified: the wheel
  builds, installs, and finds its bundled data files; the host test suite passes.
- **Arch `PKGBUILD`** in `packaging/arch/`, the starting point for an AUR package.
  Not yet published to the AUR, and not yet installed and run end to end.

### Changed
- `host.main` gained a `main()` function (used as the `view-dock` entry point);
  `python -m host.main` behaves as before.

## [2.0.1] - 2026-10-04

This release was tagged without a changelog entry; it is recorded here after the
fact. Builds from this tag still report their version as `2.0.0` in the Android
`versionName` and the iPad `MARKETING_VERSION`, because those strings were not bumped
for it. The About screen shows that version, so it reads 2.0.0 for 2.0.1 builds.

### Added
- **About and Licenses screens in both apps.** The connect screen has an About button
  showing the app version, the copyright (James Luna), the GPL "free software / no
  warranty" notices, the full GNU GPL v3 text, the licenses of the libraries bundled in
  that app, and a link to the source code. The texts are generated from `LICENSE` and
  `legal/components.json` (`python scripts/generate_legal.py`). Verified: the Android
  screens on a vivo Y28 (all three screens, scrolling, the system Back key and the
  source-code link); the iPad screens are unit-tested where possible and confirmed to be
  packaged into the project, but have not been run on a device yet.

## [2.0.0] - 2026-10-04

The headline change is the iPad's wired USB stream. It is a **major** release because an
updated iPad app is not compatible with an older host over USB — see the first entry
under *Changed*. Update the host and the iPad app together.

### Changed
- **Breaking: update the host and the iPad app together.** Over USB, the updated iPad app
  announces itself to the host with a `hello` as soon as the host connects. A host from
  v1.0.4 or earlier doesn't expect that — it takes the `hello` for the SDP answer to its
  WebRTC offer and the session fails. Wi-Fi is unaffected, and an *older* iPad app still
  works with the new host (it keeps using WebRTC). The wire protocol's own version
  (1.2) is unchanged; Android is unaffected.

- **License: GPL-3.0-or-later (was MIT).** From this release on view-dock is licensed under
  the GNU GPL v3 or later, with the copyright held by **James Luna**. Versions v1.0.0–v1.0.4
  stay available under the MIT License. Every source file now carries a license and copyright
  notice; `LICENSE` is the GPL text, `NOTICE` has the credit, the history of the MIT releases
  and the rule about the name and icon, and `THIRD_PARTY_NOTICES.md` lists the libraries used
  and their licenses (all GPL-compatible). Contributions are accepted under the terms in
  `CONTRIBUTING.md`.

### Added
- **iPad wired stream.** Verified on an iPad Air 11" (M3). The iPad app can now take the
  same wired H.264 stream as Android over its USB cable, with no Wi-Fi: the
  app announces support with a `hello`, the host (protocol 1.2+) detects it and
  streams through the tunnel, and `AVSampleBufferDisplayLayer` decodes it. Older
  iPad builds keep using WebRTC. The app's WebSocket server now handles binary
  frames, pings and fragmented messages. Unit tests for the Swift protocol,
  WebSocket framing and H.264 parsing run with `swift test` (macOS or Linux).
  **Update the host and the iPad app together:** over USB, the updated app needs the
  updated host.

- App icons: the iPad app now has one (it had none), and the host icon is
  redrawn, all derived from a single master (`branding/icon.svg`, the Android
  icon's design) so the three platforms match. The host's tray icon, which used
  to be a bare status dot, now shows that icon with a status badge.

- The USB (wired) stream now runs at 60 fps by default (it was capped at 30 by the
  WebRTC setting), via a capture → convert → encode pipeline, with a
  `VIEWDOCK_WIRED_FPS` override and per-stage timings in the log. On X11 the
  capture now skips the RGB reorder copy and the conversion reads the raw BGRA
  buffer directly, cutting the per-frame cost roughly in half (measured: capture
  ~6 → 2.4 ms, convert ~16 → 6.6 ms).

### Fixed
- The iPad app icon is now actually packaged into the app: `project.yml` listed the
  asset catalog under a `resources:` key XcodeGen doesn't have and silently
  ignores, so the app shipped with no icon. It is now under `sources`.

### Known limitations
- Touch moves the host's shared pointer rather than acting as a touchscreen
  bound to the virtual display's region.
- No Apple Pencil / stylus pressure or hover (the host injects position and
  contact only).
- Android apps are built from source (debug builds); the app is landscape-only
  and tested on a single device.
- iPad: not re-checked since the wired stream was added — Wi-Fi-only mode and the app
  being in the background. (Unplugging and replugging the cable mid-session works.)
- No Wi-Fi discovery — the host's IP is typed into the app by hand.
- X11 only; no Wayland support on the host.
- No authentication or pairing on either transport — see
  [SECURITY.md](SECURITY.md).

## [1.0.4] - 2026-10-04

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

### Documentation
- iPad client guide, the list of supported iPad models, and a list of other Linux
  distributions that should work but are untested.

## [1.0.3] - 2026-10-02

### Added
- The host now forces a spare display connector on by itself when it starts, so
  `force-connector.sh` no longer has to be run by hand after every boot. If the only
  free outputs are disconnected it forces one on at the DRM level, using
  passwordless `sudo` or a graphical `pkexec` prompt.
  - It prefers high-numbered DisplayPort outputs over HDMI, so a real monitor on HDMI
    works alongside the virtual display, and prefers already-connected free outputs
    over disconnected ones (this fixed a black screen caused by picking an unforced
    output).
  - It warns when a real monitor is plugged into the port the virtual display is
    using, since that would mirror it.
  - An opt-in live handoff (`VIEWDOCK_AUTO_HANDOFF=1`) can move the virtual display to
    another output. Experimental and untested against real hotplugs.
  - The real-monitor check runs only on RandR layout changes, so it never adds a
    periodic stall to frame capture.

## [1.0.2] - 2026-10-02

### Added
- Streaming quality and responsiveness work for the WebRTC (Wi-Fi) stream:
  - H.264 encoder tuning for desktop text (`streaming/encoder_tuning.py`) instead of
    aiortc's webcam-oriented defaults.
  - Adaptive bitrate driven by RTT and packet loss from the host's own RTCP reports
    (`streaming/bitrate_controller.py`): it backs off quickly and probes upward slowly.
  - A `pipeline:` log line every 5 s with fps, capture/convert/encode time, RTT, loss
    and the current bitrate (`streaming/metrics.py`).
  - Capture pacing that drops missed slots and resyncs, instead of aiortc's habit of
    bursting back-to-back frames after a stall (a visible hitch plus added latency).
  - `VIEWDOCK_*` environment variables to tune bitrate range, x264 preset, frame rate,
    keyframe interval and codec; documented in `host/README.md`.

## [1.0.1] - 2026-10-02

### Fixed
- A transient error while drawing the mouse cursor (seen: a one-off XFixes `BadAccess`
  right after a display rearrangement) no longer disables the cursor overlay for the
  rest of the session. It now gives up only after 120 consecutive failures
  (about 2 s at 60 fps).

### Documentation
- Troubleshooting section in `host/README.md`.

## [1.0.0] - 2026-10-01

First release.

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

[Unreleased]: https://github.com/JamesLunaa/view-dock/compare/v2.0.3...HEAD
[2.0.3]: https://github.com/JamesLunaa/view-dock/compare/v2.0.2...v2.0.3
[2.0.2]: https://github.com/JamesLunaa/view-dock/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/JamesLunaa/view-dock/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/JamesLunaa/view-dock/compare/v1.0.4...v2.0.0
[1.0.4]: https://github.com/JamesLunaa/view-dock/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/JamesLunaa/view-dock/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/JamesLunaa/view-dock/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/JamesLunaa/view-dock/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/JamesLunaa/view-dock/releases/tag/v1.0.0
