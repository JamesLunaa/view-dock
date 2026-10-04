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

Which flow a connection uses is decided by the host's first message: an SDP
envelope (`{"sdp": ..., "type": "offer"}`) starts a WebRTC session, a `hello`
starts a wired session. The host sends `hello` and `display_info` first, and
the first video frame is always a keyframe.

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
