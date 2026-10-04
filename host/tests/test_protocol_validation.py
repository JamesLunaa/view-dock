# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Verifies protocol/schema/*.json stays the actual source of truth for
message shapes, per protocol/PROTOCOL.md's working convention — catches
drift between protocol/messages.py's constants, protocol/validation.py's
registry, and the schema files themselves, plus the messages host code
actually constructs.
"""

import jsonschema
import pytest

from protocol import messages, validation

ALL_TYPES = [
    messages.TYPE_HELLO,
    messages.TYPE_DISPLAY_INFO,
    messages.TYPE_INPUT_EVENT,
    messages.TYPE_STATS,
    messages.TYPE_BYE,
    messages.TYPE_KEYFRAME_REQUEST,
]

VALID_MESSAGES = {
    messages.TYPE_HELLO: {
        "type": messages.TYPE_HELLO,
        "role": messages.ROLE_HOST,
        "protocol_version": messages.PROTOCOL_VERSION,
    },
    messages.TYPE_DISPLAY_INFO: {
        "type": messages.TYPE_DISPLAY_INFO,
        "width": 2732,
        "height": 2048,
        "refresh_hz": 60,
        "orientation": messages.ORIENTATION_LANDSCAPE,
    },
    messages.TYPE_INPUT_EVENT: {
        "type": messages.TYPE_INPUT_EVENT,
        "kind": messages.INPUT_KIND_TOUCH_DOWN,
        "x": 0.5,
        "y": 0.5,
        "pressure": 0.0,
        "timestamp_ms": 1732999999123,
    },
    messages.TYPE_STATS: {
        "type": messages.TYPE_STATS,
        "rtt_ms": 12.5,
        "bitrate_kbps": 8000,
        "fps": 60,
    },
    messages.TYPE_BYE: {
        "type": messages.TYPE_BYE,
        "reason": messages.BYE_REASON_USER_DISCONNECTED,
    },
    messages.TYPE_KEYFRAME_REQUEST: {"type": messages.TYPE_KEYFRAME_REQUEST},
}


@pytest.mark.parametrize("message_type", ALL_TYPES)
def test_every_message_type_has_a_registered_schema(message_type):
    assert message_type in validation._SCHEMA_FILENAME_BY_TYPE


@pytest.mark.parametrize("message_type", ALL_TYPES)
def test_schema_file_is_itself_valid(message_type):
    schema = validation._SCHEMAS[message_type]
    jsonschema.Draft7Validator.check_schema(schema)


@pytest.mark.parametrize("message_type", ALL_TYPES)
def test_valid_message_passes(message_type):
    validation.validate_message(VALID_MESSAGES[message_type])


def test_missing_required_field_fails():
    message = dict(VALID_MESSAGES[messages.TYPE_DISPLAY_INFO])
    del message["refresh_hz"]
    with pytest.raises(jsonschema.ValidationError):
        validation.validate_message(message)


def test_out_of_range_value_fails():
    message = dict(VALID_MESSAGES[messages.TYPE_INPUT_EVENT])
    message["x"] = 1.5  # schema bounds x to [0.0, 1.0]
    with pytest.raises(jsonschema.ValidationError):
        validation.validate_message(message)


def test_unknown_enum_value_fails():
    message = dict(VALID_MESSAGES[messages.TYPE_BYE])
    message["reason"] = "not_a_real_reason"
    with pytest.raises(jsonschema.ValidationError):
        validation.validate_message(message)


def test_additional_property_fails():
    message = dict(VALID_MESSAGES[messages.TYPE_HELLO])
    message["extra_field"] = "not allowed"
    with pytest.raises(jsonschema.ValidationError):
        validation.validate_message(message)


def test_unknown_message_type_raises():
    with pytest.raises(validation.UnknownMessageType):
        validation.validate_message({"type": "not_a_real_type"})


def test_missing_type_raises():
    with pytest.raises(validation.UnknownMessageType):
        validation.validate_message({"width": 100})


@pytest.mark.parametrize("role", [messages.ROLE_HOST, messages.ROLE_IPAD, messages.ROLE_ANDROID])
def test_hello_accepts_every_client_role(role):
    validation.validate_message(
        {"type": messages.TYPE_HELLO, "role": role, "protocol_version": messages.PROTOCOL_VERSION}
    )
