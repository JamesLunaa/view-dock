# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""JSON Schema validation against `protocol/schema/*.json` — the source of
truth for message shapes per `protocol/PROTOCOL.md`, which already asks both
implementations to validate against these during development. Only `host`
can actually do this at runtime (no `jsonschema` equivalent wired into the
`ipad` Swift side), but it still catches protocol drift on this side, and
backs the test suite in `host/tests/`.
"""

import json
from pathlib import Path

import jsonschema

from protocol import messages

_SCHEMA_DIR = Path(__file__).parent / "schema"

_SCHEMA_FILENAME_BY_TYPE = {
    messages.TYPE_HELLO: "hello.json",
    messages.TYPE_DISPLAY_INFO: "display_info.json",
    messages.TYPE_INPUT_EVENT: "input_event.json",
    messages.TYPE_STATS: "stats.json",
    messages.TYPE_BYE: "bye.json",
    messages.TYPE_KEYFRAME_REQUEST: "keyframe_request.json",
}


def _load_schema(filename: str) -> dict:
    return json.loads((_SCHEMA_DIR / filename).read_text())


_SCHEMAS = {
    message_type: _load_schema(filename)
    for message_type, filename in _SCHEMA_FILENAME_BY_TYPE.items()
}


class UnknownMessageType(ValueError):
    pass


def validate_message(message: dict) -> None:
    """Raises `UnknownMessageType` if `message["type"]` isn't one of
    `protocol/messages.py`'s TYPE_* constants, or `jsonschema.ValidationError`
    if it doesn't conform to that type's schema.
    """
    message_type = message.get("type")
    schema = _SCHEMAS.get(message_type)
    if schema is None:
        raise UnknownMessageType(f"Unknown or missing message type: {message_type!r}")
    jsonschema.validate(instance=message, schema=schema)
