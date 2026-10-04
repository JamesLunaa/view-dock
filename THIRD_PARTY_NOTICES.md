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
| Java-WebSocket | MIT |
| kotlinx.coroutines | Apache-2.0 |
| AndroidX / Jetpack Compose | Apache-2.0 |

## iPad app (`ipad/project.yml`)

| Library | License |
|---|---|
| WebRTC framework binaries (stasel/WebRTC) | BSD-3-Clause |

## Build tooling (not shipped inside the apps)

XcodeGen (MIT) generates the Xcode project; the Gradle wrapper (Apache-2.0) builds the
Android app.
