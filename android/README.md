# android

Native Android app (Kotlin + Jetpack Compose) for phones and tablets. Renders
the WebRTC video stream from `host/` full-screen and forwards touch/stylus
input back over the `control` data channel, per `protocol/PROTOCOL.md`. It is
the Android counterpart of `ipad/` and speaks the same protocol.

## Status

Supported. Tested on one device: a vivo Y28 (V2352) running Funtouch OS 15
(Android 15), over both USB and Wi-Fi. `minSdk` is 26 (Android 8.0); other
devices, Android versions and tablets should work in principle but are
untested. Known limits:

- Landscape only.
- The host ignores stylus pressure for now (the app sends it).
- Wi-Fi discovery (mDNS, via `NsdManager`) works on the vivo Y28 (reported); if your
  network blocks it, type the host's IP.
- Debug builds only; no signed release or Play Store listing yet.
- Touch moves the host's shared pointer rather than acting as a touchscreen
  bound to the virtual display (same as the iPad).

## About and Licenses

The connect screen has an **About** button (top right): the app's version and copyright
(James Luna), the GPL notices, the full GNU GPL v3 text, the licenses of the libraries
inside the app, and a link to the source code. The texts are bundled in
`app/src/main/assets/legal/` and are **generated** — edit `legal/components.json` and run
`python scripts/generate_legal.py`, don't change them by hand. (Checked on a vivo Y28: the
screens, scrolling, the system Back key, and the source-code link, which opens in whatever
app handles GitHub links.)

## Building

Requires a JDK 17+ (21 recommended) and the Android SDK with platform 37 and
build-tools installed. Point Gradle at the SDK once:

```sh
echo "sdk.dir=$HOME/Android/Sdk" > local.properties
```

Then build a debug APK (installable without a signing key):

```sh
cd android
./gradlew assembleDebug
# -> app/build/outputs/apk/debug/app-debug.apk
./gradlew testDebugUnitTest   # protocol + touch-mapping unit tests
```

Install onto a connected device (USB debugging on):

```sh
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

`minSdk` is 26 (Android 8.0). The debug APK bundles libwebrtc for every ABI,
which makes it large; restrict `abiFilters` in `app/build.gradle.kts` for a
slimmer build once the target devices are known.

## Connecting

**Wi-Fi.** Put the device and the host on the same network, start the host,
and tap your computer in the list the app shows (it is found automatically). If
nothing appears, type the host's IP into the app and tap *Connect over Wi-Fi*.

**USB.** Enable *Developer options → USB debugging* on the device, plug it in
and accept the "Allow USB debugging?" prompt. With `adb` installed on the host
(Arch: `android-tools`) the host detects the device automatically and prefers
it over Wi-Fi. Open the app; it listens on a loopback port that the host
reaches through `adb forward`.

Over USB the whole session — H.264 video and input events — travels through
the cable (`adb forward` is TCP-only, so this is a plain stream rather than
WebRTC; see "Wired stream" in `protocol/PROTOCOL.md`). Wi-Fi is not used at
all, so it works on a network where devices can't reach each other. Keep the
app in the foreground: while it is in the background the picture pauses (the
decoder loses its surface) and is meant to resume with a fresh keyframe when
you return — this hasn't been tested. Video is 20 Mbps by default
(`VIEWDOCK_WIRED_BITRATE_MBPS` on the host).

## Layout

- `app/src/main/java/dev/viewdock/android/protocol/` — message constants and
  builders, mirroring `protocol/messages.py`.
- `.../net/` — `ConnectionManager` (picks Wi-Fi vs. USB, mirroring
  `host/transport/`), `SignalingChannel` (the two signaling transports),
  `WebRtcClient` (Wi-Fi: peer connection, video track, control data channel)
  and `WiredClient` + `H264Decoder` (USB: hardware-decoded video straight
  off the tunnel).
- `.../input/` — `TouchInputForwarder`, turning `MotionEvent`s into
  `input_event` messages (stylus → `pencil_*`).
- `.../ui/` — the Compose screens.
