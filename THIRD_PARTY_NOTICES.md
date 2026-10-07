# Third-party notices

view-dock is licensed under the GPL-3.0-or-later (see [LICENSE](LICENSE) and
[NOTICE](NOTICE)). It uses the open-source libraries below, each under its own
license. All of them are compatible with the GPL-3.0-or-later. Versions are the
ones the project is built against at the time of writing; the authoritative
license text is the one shipped with each library.

If you distribute a built app, keep these notices with it — for the Android and iPad
apps, typically on an in-app Licenses screen.

## Host (Python, `host/requirements.txt`)

| Library | License |
|---|---|
| aiortc | BSD-3-Clause |
| PyAV (`av`) | BSD-3-Clause (bundles FFmpeg and libx264, which are LGPL/GPL — compatible with this project's GPL) |
| websockets | BSD-3-Clause |
| zeroconf (Wi-Fi discovery) | LGPL-2.1-or-later |
| jsonschema | MIT |
| mss | MIT |
| numpy | BSD-3-Clause (and others for bundled parts) |
| python-xlib | LGPL-2.1-or-later |
| python-uinput | GPL-3.0-or-later |
| PySide6 (optional GUI) | LGPL-3.0 / GPL-3.0 |
| pytest (tests only) | MIT |

## Android app (`android/gradle/libs.versions.toml`)

| Library | License |
|---|---|
| stream-webrtc-android (prebuilt WebRTC) | Apache-2.0 |
| WebRTC (inside stream-webrtc-android) | BSD-3-Clause |
| Java-WebSocket | MIT |
| SLF4J API (brought in by Java-WebSocket) | MIT |
| AndroidX / Jetpack Compose | Apache-2.0 |
| Kotlin standard library, kotlinx.coroutines, kotlinx.serialization | Apache-2.0 |
| JetBrains Annotations, JSpecify, Guava ListenableFuture | Apache-2.0 |

## iPad app (`ipad/project.yml`)

| Library | License |
|---|---|
| WebRTC framework binaries (stasel/WebRTC) | BSD-3-Clause |
| WebRTC (inside the framework) | BSD-3-Clause |

## In the apps

Both apps show these notices, with the full license texts, on their **About → Third-party
licenses** screen. That text is generated from [`legal/components.json`](legal/components.json)
(and the texts in `legal/licenses/`) by `python scripts/generate_legal.py` — edit those, not the
bundled copies. WebRTC itself contains further components (for example BoringSSL, libvpx,
libyuv, Opus, abseil-cpp) under their own permissive licenses; the apps point to this in
their notices but do not reproduce each of those separately.

## Build tooling (not shipped inside the apps)

XcodeGen (MIT) generates the Xcode project; the Gradle wrapper (Apache-2.0) builds the
Android app.
