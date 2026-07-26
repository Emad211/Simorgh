from __future__ import annotations

import math

import pytest

from simorgh_core.agents.invocations import (
    InvocationPayloadError,
    canonical_fingerprint,
    canonical_json,
)


def test_canonical_json_and_sha_are_order_stable() -> None:
    left = {"z": 1, "a": {"x": "سیمرغ"}}
    right = {"a": {"x": "سیمرغ"}, "z": 1}
    assert canonical_json(left) == canonical_json(right)
    assert canonical_fingerprint(left) == canonical_fingerprint(right)


def test_non_json_payload_fails_without_private_echo_or_cause() -> None:
    private_marker = "PRIVATE_CANONICAL_JSON_41a7"
    with pytest.raises(InvocationPayloadError) as raised:
        canonical_json({"private": private_marker, "value": math.nan})
    assert private_marker not in str(raised.value)
    assert raised.value.__cause__ is None

    with pytest.raises(InvocationPayloadError) as object_error:
        canonical_json({"private": private_marker, "value": object()})
    assert private_marker not in str(object_error.value)
    assert "object at" not in str(object_error.value)
    assert object_error.value.__cause__ is None

    with pytest.raises(InvocationPayloadError):
        canonical_json({"value": ("tuple-is-not-json",)})
    with pytest.raises(InvocationPayloadError):
        canonical_json({1: "non-string-key"})  # type: ignore[dict-item]


def test_lone_surrogates_in_values_and_keys_are_rejected_without_echo() -> None:
    private_marker = "PRIVATE_SURROGATE_3f719"
    lone_surrogate = chr(0xD800)
    with pytest.raises(InvocationPayloadError) as value_error:
        canonical_json({"private": private_marker, "value": lone_surrogate})
    with pytest.raises(InvocationPayloadError) as key_error:
        canonical_json({lone_surrogate: private_marker})
    assert private_marker not in str(value_error.value)
    assert private_marker not in str(key_error.value)
    assert value_error.value.__cause__ is None
    assert key_error.value.__cause__ is None
