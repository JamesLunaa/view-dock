# Security Policy

## Reporting a vulnerability

Please report security issues privately, **not** as a public issue:

- Use GitHub's private vulnerability reporting — the **Report a vulnerability**
  button under this repository's [Security tab](https://github.com/JamesLunaa/view-dock/security).

Include what you were able to do, which side you were attacking (host, iPad app,
Android app, or the network between them), and the transport in use (Wi-Fi or USB). A
proof-of-concept is welcome but not required.

Expect a first response within a week. This is a small hobby project
maintained by one person — there is no SLA beyond best effort, but reports
will be acknowledged and triaged rather than ignored.

## Supported versions

Pre-1.0, with no released versions yet. Only the current `master` is
supported; fixes land there rather than being backported.

## Security model

Read this before running view-dock on a network you don't control. The
summary: **view-dock currently assumes a trusted LAN and an attacker-free
local network. There is no authentication of any kind.**

### What is protected

- **Every WebRTC session is encrypted.** Video rides SRTP and the
  `control` data channel rides SCTP-over-DTLS, both keyed by the mandatory
  DTLS handshake. This is not optional and there is no plaintext fallback —
  it comes from WebRTC itself (`aiortc` on the host, Google's WebRTC
  framework on the iPad and Android). A passive observer on the LAN cannot
  read your screen contents off the wire. This covers Wi-Fi sessions and the
  iPad.
- **Android over USB is not WebRTC, and is not encrypted — but never touches
  the network.** The wired stream (`host/streaming/wired_session.py`,
  protocol "Wired stream") is plain H.264 and JSON on a WebSocket that
  `adb forward` carries over the USB cable. The app's listener
  (`UsbSignaling` in `android/`) binds `127.0.0.1` only, so unlike the iPad's
  (below) it cannot be reached from the Wi-Fi network. What a USB session
  does rely on is the physical cable and the phone's USB debugging
  authorization: anyone who can run `adb` against an authorized device can
  already do far more than view this stream.
- **Input events are schema-validated and bounded.** Every `control` message
  is validated against `protocol/schema/*.json` before it is acted on, and
  malformed messages are dropped (`host/streaming/webrtc_session.py`).
  Injected input is limited to absolute pointer coordinates in `[0, 1]`,
  mapped inside the virtual display, plus `BTN_TOUCH` — the uinput device
  (`host/input/injector.py`) declares no keyboard capability, so no message
  can synthesize keystrokes.
- **The host runs unprivileged.** No component runs as root. `sudo` is
  needed only for one-time/per-boot setup outside the running app (loading
  `uinput`, forcing a DRM connector).

### What is not protected

- **No authentication, no pairing.** Neither side proves who it is. The host
  accepts the first client that completes the signaling handshake
  (`host/transport/wifi.py` — "first connection wins").
- **Signaling is plaintext `ws://`.** The SDP offer/answer exchange that
  bootstraps the session has no TLS and no origin checks. Over Wi-Fi the
  host listens on `0.0.0.0:8765`, reachable from anywhere on the LAN.
- **Therefore, on Wi-Fi, anyone who can reach port 8765 can take the
  session.** Connecting before (or instead of) your iPad gets them a live
  stream of the extended display and the ability to send `input_event`
  messages that move the host's pointer and click. That is remote view plus
  remote clicking on your desktop, from an unauthenticated peer.
- **DTLS fingerprints travel in that same unauthenticated channel**, so
  encryption protects against passive sniffing but not against an active
  attacker who can intercept and rewrite signaling — they can substitute
  their own fingerprint and sit in the middle.
- **The iPad's USB listener is not USB-only** (the Android app's is: it
  binds loopback only). For the wired transport the
  iPad is the server (`ipad/Sources/Networking/WebSocketServer.swift`), and
  its `NWListener` on port 8766 binds all interfaces — while the app is
  waiting for a host, another device on the same Wi-Fi network can connect
  to it and feed it a session. USB itself still requires a physically
  cabled, trust-paired device.
- **Dependencies are third-party and not vendored.** The host pulls
  `aiortc`/`av`/`numpy` and friends from PyPI; the iPad app pulls a
  prebuilt WebRTC binary framework from
  [stasel/WebRTC](https://github.com/stasel/WebRTC); the Android app pulls
  prebuilt WebRTC (`stream-webrtc-android`) and `Java-WebSocket` from Maven
  Central. All are trusted as-is.

### Practical advice

- Run it on a home/trusted network, or a network segment you control.
- Prefer USB when you can. It still has no authentication, but reaching the
  host's side of the tunnel requires a cable and an iOS trust pairing (or,
  on Android, an accepted USB-debugging authorization) — and the Android USB
  stream stays off the network entirely.
- If you are on a shared or public network, firewall the host port, e.g.
  limit `8765/tcp` to your device's address, or don't run it at all.
- Close the host when you're not using it. The Wi-Fi listener is open for
  as long as a session is running or waiting.

### Known gaps, tracked as future work

These are acknowledged weaknesses rather than disputed reports — you don't
need to report them, though a concrete attack that goes beyond them is
certainly worth reporting:

- No pairing/authentication step (a shared secret or QR-displayed token
  bound into the signaling handshake, and ideally into DTLS fingerprint
  verification).
- No TLS on the signaling channel.
- The iPad's USB-mode listener should be bound to the loopback/USB interface
  rather than all interfaces.
- No rate limiting on injected input events.
