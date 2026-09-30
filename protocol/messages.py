"""Shared message-type constants for the view-dock wire protocol.

Mirrors protocol/PROTOCOL.md and protocol/schema/*.json. Imported by the
`host` package. The `ipad` Swift app keeps an equivalent set of constants in
its own source (see ipad/Sources/Protocol/Messages.swift) since Swift can't
import this module directly — keep the two in sync by hand when this file
changes.
"""

PROTOCOL_VERSION = "1.0"

TYPE_HELLO = "hello"
TYPE_DISPLAY_INFO = "display_info"
TYPE_INPUT_EVENT = "input_event"
TYPE_STATS = "stats"
TYPE_BYE = "bye"

ROLE_HOST = "host"
ROLE_IPAD = "ipad"

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
