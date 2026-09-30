# view-dock wire protocol

Transport-agnostic contract between `host` (Python, Arch Linux) and `ipad`
(Swift, iPadOS). The same message set is used whether the underlying connection
is a Wi-Fi WebRTC session or a usbmuxd-tunneled USB connection — only how the
WebRTC signaling handshake is bootstrapped differs per transport.

All control messages are JSON objects sent over the WebRTC data channel named
`control`. Video rides a separate WebRTC media track. Schemas for each message
type live in `protocol/schema/` as JSON Schema documents; both `host` and
`ipad` implementations should validate against these during development.

## Message types

### `hello` (either → either)
Sent immediately after the data channel opens, before any other message.

```json
{ "type": "hello", "role": "host" | "ipad", "protocol_version": "1.0" }
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

### `bye` (either → either)
Graceful disconnect notice before closing the connection.

```json
{ "type": "bye", "reason": "user_disconnected" | "error" | "shutdown" }
```

## Versioning

`protocol_version` uses `major.minor`. Breaking changes bump `major`; both
sides must reject a `hello` with a `major` they don't support. Additive,
backward-compatible fields bump `minor` only.

## Working convention

Changes here are cross-cutting: update `host` and `ipad` implementations in
the same change, and treat this document (plus `protocol/schema/`) as the
source of truth rather than letting either side's implementation drift from it.
