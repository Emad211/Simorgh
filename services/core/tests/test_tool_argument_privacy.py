from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from simorgh_core.agents.tool_gateway import ToolCallRequest


def test_tool_arguments_reject_non_json_without_private_echo() -> None:
    private_marker = "PRIVATE_TOOL_ARGUMENT_40bc"
    with pytest.raises(ValidationError) as raised:
        ToolCallRequest(
            invocation_id="11111111-1111-1111-1111-111111111111",
            request_id="22222222-2222-2222-2222-222222222222",
            agent_id="github.read",
            agent_version="1.0.0",
            tool_id="github.search",
            connector_id="github",
            allowed_data_sources=frozenset({"github"}),
            arguments={"private": private_marker, "value": math.nan},
        )
    assert private_marker not in str(raised.value)
    assert "tool arguments must be strict JSON data" in str(raised.value)


def test_tool_arguments_enforce_canonical_byte_limit_without_value_echo() -> None:
    private_marker = "PRIVATE_OVERSIZED_ARGUMENT_a991"
    with pytest.raises(ValidationError) as raised:
        ToolCallRequest(
            invocation_id="11111111-1111-1111-1111-111111111111",
            request_id="22222222-2222-2222-2222-222222222222",
            agent_id="github.read",
            agent_version="1.0.0",
            tool_id="github.search",
            connector_id="github",
            allowed_data_sources=frozenset({"github"}),
            arguments={"private": private_marker + "x" * 256_001},
        )
    assert private_marker not in str(raised.value)
    assert "256000-byte limit" in str(raised.value)
