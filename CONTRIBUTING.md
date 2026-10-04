# Contributing

Contributions, ideas, and feedback are welcome. If you're tackling one of the
known limitations in the README or something adjacent, open an issue first
to compare notes — some of these (touch-as-a-real-touchscreen especially)
have real design tradeoffs worth discussing before diving into an
implementation.

**Security issues are the exception**: don't open a public issue for them.
See [SECURITY.md](SECURITY.md).

## How the pieces fit together

Worth skimming before your first change, because a lot of work touches two
sides at once:

| Directory | What it is | Dive deeper |
|---|---|---|
| `host/` | Python server on the Arch machine: virtual display, capture, encoding, WebRTC, input injection, three front-ends (GUI/TUI/CLI). | [`host/README.md`](host/README.md) |
| `ipad/` | Native iPadOS app (SwiftUI + WebRTC), generated from `project.yml` by XcodeGen. | [`ipad/README.md`](ipad/README.md) |
| `android/` | Native Android app (Kotlin + Jetpack Compose, Gradle). | [`android/README.md`](android/README.md) |
| `protocol/` | The wire contract between host and apps: message types, JSON Schemas, the wired stream. | [`protocol/PROTOCOL.md`](protocol/PROTOCOL.md) |

Inside `host/`, the layering is: `displayserver/` (create and capture a
virtual display, behind a per-display-server interface), `transport/`
(Wi-Fi, iPad USB via usbmuxd, and Android USB via `adb`, behind a common
`Transport` base),
`streaming/` (one session: a WebRTC video track + `control` data channel, or
for Android over USB the wired H.264 stream),
`input/` (uinput injection), with `runner.py`/`main.py` wiring them together
and `gui/` + `ui/` as alternative front-ends over the same runner. Changes
that stay inside one of those boxes are the easy ones; anything crossing
`protocol/` is the cross-cutting case below.

## Dev setup

Follow the host setup steps in the [README](README.md#1-host-setup-on-the-arch-linux-machine)
to get a working `.venv` with `host/requirements.txt` installed. For the
iPad app, see [`ipad/README.md`](ipad/README.md); for the Android app, see
[`android/README.md`](android/README.md) (it builds on Linux with just a JDK
and the Android SDK).

The host runs three ways, all on the same underlying runner — use whichever
suits what you're debugging:

```sh
python -m host.gui     # PySide6 tray applet + window (needs PySide6)
python -m host.ui      # curses terminal UI, works over SSH
python -m host.main    # raw CLI, most useful for logs and scripting
```

You don't need an iPad connected to work on most of the host: the test
suite mocks the hardware out, and `host/displayserver/test_pattern.py`
exists so the capture/streaming path can be exercised without a real
desktop in front of it.

## Running tests

The host test suite is pure Python and mocks out hardware (uinput, X11,
subprocess calls), so it runs headless without an actual display or iPad
connected:

```sh
source .venv/bin/activate
python -m pytest host/tests
```

CI (`.github/workflows/tests.yml`) runs this same suite on every push and
pull request, installing from the lock file described below.

The Android app has JVM unit tests (protocol messages and touch-coordinate
mapping) that need no device:

```sh
cd android && ./gradlew testDebugUnitTest
```

The iPad app's Foundation-only logic (protocol messages, WebSocket framing,
H.264 Annex-B parsing) has unit tests that run without Xcode or a device, on
macOS or Linux:

```sh
cd ipad && swift test
```

CI runs the host suite only; the Android and Swift tests are run by hand for now. There
is no automated test for the video path on a real decoder — that needs a
device.

When adding tests, follow what's already in `host/tests/`: each module
targets one unit (`test_runner.py`, `test_usb_transport.py`, …), external
commands and devices are patched rather than invoked, and the docstring at
the top says which real-world failure the test is pinning down. Several of
them exist because of a specific bug — that context is worth keeping.

There's no automated test suite for the iPad app yet — changes there should
be verified by building and running on a physical device (WebRTC/video
doesn't work in the Simulator).

## Protocol changes

`protocol/` is the contract between `host/`, `ipad/` and `android/`. If you change
`protocol/schema/*.json` or `protocol/messages.py`, update both
implementations in the same PR rather than letting them drift — see
[`protocol/PROTOCOL.md`](protocol/PROTOCOL.md). Concretely, a new or changed
message means touching all five of:

1. `protocol/schema/<type>.json` — the schema, which the host validates
   against at runtime.
2. `protocol/messages.py` — the shared constants.
3. `ipad/Sources/Protocol/Messages.swift` — the Swift mirror of those
   constants (Swift can't import the Python module, so this is hand-synced).
   Its tests (`ipad/Tests/`) check the JSON shapes against what the host's
   schemas allow.
4. `android/app/src/main/java/dev/viewdock/android/protocol/Messages.kt` — the
   Kotlin mirror (hand-synced too).
5. `protocol/PROTOCOL.md` — the prose description and example payload.

Then the code on both sides that sends or handles it, plus a
[CHANGELOG.md](CHANGELOG.md) entry noting the protocol change, since it
affects whether a given host and app version interoperate.

## App icons

One master, `branding/icon.svg`, drives the host, iPad and Android icons so
they stay consistent. Edit it (it's plain SVG, three elements by id) and run:

```sh
python branding/generate_icons.py   # needs PySide6, like the host GUI
```

That rewrites `host/gui/assets/icon.png`, the iPad's
`Assets.xcassets/AppIcon.appiconset` and Android's launcher drawable and
background colour — commit the results with the master. A host test fails if
they get out of step.

## Code style

There's no formatter or linter enforced in CI. Match the surrounding code:
standard library ordering, type hints on function signatures, and comments
that explain *why* a non-obvious thing is done rather than restating the
code. The existing comments carry a lot of hard-won detail about X11,
usbmuxd, and WebRTC behavior — when you change code they describe, update
them in the same commit.

## Reproducible builds

### Host

`host/requirements.txt` holds deliberately loose ranges for day-to-day
installs. `host/requirements.lock.txt` is the reproducible counterpart:
every package in the dependency tree pinned to an exact version with
hashes, resolved for Python 3.11+ across platforms.

```sh
pip install --require-hashes -r host/requirements.lock.txt
```

That's what CI installs, so a green CI run corresponds to an exactly known
dependency set. It excludes PySide6 (the optional GUI, ~500MB, not needed
by the CLI, the TUI, or the tests) — `pip install PySide6` separately if you
want `python -m host.gui`.

Regenerate the lock whenever you change `host/requirements.txt`; the
command, and the one manual step after it, are in the lock file's own
header comment. Dependabot will also open PRs against both files weekly.

### Android

- Gradle is pinned through the checked-in wrapper (`android/gradlew`,
  `gradle/wrapper/gradle-wrapper.properties`), and every dependency version
  lives in `android/gradle/libs.versions.toml`, so the same commit builds
  with the same libraries. It needs JDK 17 or later and the Android SDK
  (platform 37 — the newest Compose requires it to compile; the app itself
  targets API 35).
- The WebRTC dependency (`stream-webrtc-android`) is a prebuilt binary, like
  the iPad's.
- `android/local.properties` (your SDK path) and `build/` are gitignored.

### iPad

The app is less reproducible than the host, in two places worth knowing
about:

- The Xcode project isn't checked in — `ipad/project.yml` + `xcodegen
  generate` produce it. Same input, same project, but XcodeGen's own version
  can affect the output, so note the version you used if a build problem
  turns out to be project-level.
- The WebRTC dependency is declared as `from: 137.0.0`, which allows any
  137.x. Swift Package Manager records the exact resolved version in
  `Package.resolved` inside the generated `.xcodeproj`, which is gitignored
  — so two people can build the same commit against different WebRTC
  patch releases. If you hit a WebRTC-level difference, compare resolved
  versions first. Dependabot can't watch this dependency either (it's an
  XcodeGen manifest, not a `Package.swift`), so bumps are manual.

## Pull requests

Keep PRs focused on one change. Fill out the PR template — in particular,
note whether you verified the change on real hardware, since the test suite
doesn't cover the capture/streaming/input pipeline end-to-end.

CI runs the host tests, CodeQL analysis, and a dependency review on changed
dependencies. All three should be green before merge.

Add a [CHANGELOG.md](CHANGELOG.md) entry under `## [Unreleased]` for
anything a user would notice: new behavior, changed setup steps, fixed bugs,
new requirements. Pure refactors and internal cleanups don't need one.

## Releases

Releases are cut from `master` by the maintainer:

1. Move the `## [Unreleased]` entries into a new `## [X.Y.Z] - YYYY-MM-DD`
   section in `CHANGELOG.md`, leaving `Unreleased` empty, and update the
   link definitions at the bottom.
2. Tag the commit: `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`.
3. Publish a GitHub release from that tag, using the changelog section as
   its notes.

Versions follow semver, with the protocol in mind: since the host and the
iPad app are installed separately, a release containing a breaking
`protocol/` change is the kind that needs a major (or, pre-1.0, minor)
bump and a note that both sides must be updated together.
