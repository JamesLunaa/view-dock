"""Shared message-type constants for the view-dock wire protocol.

Mirrors protocol/PROTOCOL.md and protocol/schema/*.json. Imported by the
`host` package. The `ipad` Swift app and the `android` Kotlin app keep
equivalent sets of constants in their own source
(ipad/Sources/Protocol/Messages.swift, android/app/src/main/java/dev/viewdock/android/protocol/Messages.kt)
since neither can import this module directly — keep them in sync by hand
when this file changes.
"""

PROTOCOL_VERSION = "1.2"

TYPE_HELLO = "hello"
TYPE_DISPLAY_INFO = "display_info"
TYPE_INPUT_EVENT = "input_event"
TYPE_STATS = "stats"
TYPE_BYE = "bye"
TYPE_KEYFRAME_REQUEST = "keyframe_request"

# Wired stream (see "Wired stream" in protocol/PROTOCOL.md): the first byte of
# every binary frame says what it carries. Only video exists so far.
WIRED_FRAME_VIDEO = 0x01
WIRED_FLAG_KEYFRAME = 0x01
WIRED_VIDEO_HEADER_SIZE = 10  # type(1) + flags(1) + pts_us(8, big-endian)

ROLE_HOST = "host"
ROLE_IPAD = "ipad"
ROLE_ANDROID = "android"

INPUT_KIND_TOUCH_DOWN = "touch_down"
INPUT_KIND_TOUCH_MOVE = "touch_move"
INPUT_KIND_TOUCH_UP = "touch_up"
INPUT_KIND_PENCIL_DOWN = "pencil_down"
INPUT_KIND_PENCIL_MOVE = "pencil_move"
INPUT_KIND_PENCIL_UP = "pencil_up"

ORIENTATION_LANDSCAPE = "landscape"
ORIENTATION_PORTRAIT = "portrait"

BYE_REASON_USER_DISCONNECTED = "user_disconnected"
BYE_REASON_ERROR = "error"
BYE_REASON_SHUTDOWN = "shutdown"
