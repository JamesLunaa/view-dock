# view-dock wire protocol

Transport-agnostic contract between `host` (Python, Arch Linux) and its
clients: `ipad` (Swift, iPadOS) and `android` (Kotlin, Android phones and
tablets). The same message set is used whether the underlying connection is a
Wi-Fi WebRTC session, a usbmuxd-tunneled USB connection (iOS) or an
`adb forward`-tunneled USB connection (Android) — only how the WebRTC
signaling handshake is bootstrapped differs per transport.

All control messages are JSON objects sent over the WebRTC data channel named
`control`. Video rides a separate WebRTC media track. Schemas for each message
type live in `protocol/schema/` as JSON Schema documents; both `host` and
client implementations should validate against these during development.

## Message types

### `hello` (either → either)
Sent immediately after the data channel opens, before any other message.

```json
{ "type": "hello", "role": "host" | "ipad" | "android", "protocol_version": "1.1" }
```

### `display_info` (host → ipad)
Describes the virtual display the host created, sent after `hello` and again
whenever it changes.

```json
{
  "type": "display_info",
  "width": 2732,
  "height": 2048,
  "refresh_hz": 60,
  "orientation": "landscape" | "portrait"
}
```

### `input_event` (ipad → host)
One per touch/pencil sample. Coordinates are normalized `[0.0, 1.0]` relative
to the display described in the last `display_info`, so the host maps them to
real pixels regardless of virtual display resolution.

```json
{
  "type": "input_event",
  "kind": "touch_down" | "touch_move" | "touch_up" | "pencil_down" | "pencil_move" | "pencil_up",
  "x": 0.4231,
  "y": 0.8107,
  "pressure": 0.0,
  "timestamp_ms": 1732999999123
}
```

### `stats` (either → either)
Periodic link-quality reporting, used for adaptive bitrate and debugging.

```json
{
  "type": "stats",
  "rtt_ms": 12.5,
  "bitrate_kbps": 8000,
  "fps": 60
}
```

### `keyframe_request` (client → host)
Asks the host to make its next video frame a keyframe. Only meaningful on a
wired stream (below); WebRTC has its own PLI mechanism.

```json
{ "type": "keyframe_request" }
```

### `bye` (either → either)
Graceful disconnect notice before closing the connection.

```json
{ "type": "bye", "reason": "user_disconnected" | "error" | "shutdown" }
```

### Client roles

`ipad` and `android` are interchangeable from the host's point of view; the role
only identifies which client is on the other end. `pencil_*` input kinds are
also used for an Android stylus (`MotionEvent.TOOL_TYPE_STYLUS`).

## Discovery (Wi-Fi)

Not part of the message protocol: it happens before the signaling connection. The host
advertises a DNS-SD service over mDNS (`host/transport/discovery.py`) and the apps browse
for it, then connect to the resolved address and port as if the user had typed them.

- Service type: `_viewdock._tcp` (`_viewdock._tcp.local.`), on the Wi-Fi signaling port (8765).
- Instance name: the host's hostname.
- TXT records: `protocol_version` (e.g. `1.2`; an app should refuse a different major) and
  `name` (display name, the hostname).
- Advertised on the LAN interfaces only (not loopback, Docker, libvirt, Tailscale, ...).
- Discovery is not trust: anyone on the network can advertise this service, and there is
  no authentication yet (see `SECURITY.md`), so apps list hosts and wait for a tap.

## Wired stream

Wi-Fi sessions carry video as a WebRTC media track. A wired (USB) tunnel is a
single TCP connection (`adb forward` / usbmuxd), which cannot carry WebRTC's UDP
media, so a wired session streams over that connection directly instead of
negotiating WebRTC. The same WebSocket connection that would carry the SDP
exchange carries the whole session:

- **Text frames** are the ordinary JSON control messages above (`hello`,
  `display_info`, `input_event`, `keyframe_request`, `stats`, `bye`).
- **Binary frames** (host → client) are video. Layout:

  | bytes | meaning |
  |-------|---------|
  | 0     | frame type, `0x01` = H.264 video |
  | 1     | flags, bit 0 = keyframe |
  | 2–9   | presentation timestamp in microseconds, unsigned big-endian |
  | 10…   | one H.264 access unit in Annex-B form (start codes); keyframes carry SPS/PPS in-band |

  The stream is baseline-profile H.264 with no B-frames, so decode order is
  display order.

Which flow a connection uses is decided at connect time:

- **Android over `adb`:** always wired. The app is the listener and the host
  speaks first.
- **iPad over `usbmuxd`/`iproxy`:** the host can't tell which build of the app
  is listening, so a build that supports the wired stream announces itself by
  sending `hello` (role `ipad`, `protocol_version` 1.2 or later) the moment the
  tunnel connects. The host waits about a second for it: a `hello` means wired,
  silence means an older WebRTC-only build, and the host proceeds with the SDP
  offer as before. (An app that announces itself to a host older than 1.2 will
  confuse that host — keep the two in step.)
- **Wi-Fi:** always WebRTC.

For a wired session the host then sends its own `hello` and `display_info`
first, and the first video frame is always a keyframe. The client decides on
its side by the host's first message: a `hello` is wired, an SDP envelope
(`{"sdp": ..., "type": "offer"}`) is WebRTC.

## Versioning

`protocol_version` uses `major.minor`. Breaking changes bump `major`; both
sides must reject a `hello` with a `major` they don't support. Additive,
backward-compatible fields bump `minor` only.

- **1.1** — added the `android` role value to `hello`.
- **1.2** — added the wired stream (binary video frames over the signaling
  connection) and the `keyframe_request` message.

## Working convention

Changes here are cross-cutting: update `host` and `ipad` implementations in
the same change, and treat this document (plus `protocol/schema/`) as the
source of truth rather than letting either side's implementation drift from it.
