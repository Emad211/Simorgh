from __future__ import annotations

import pytest

from simorgh_core.agents.specialist_execution import (
    SpecialistCancellation,
    SpecialistExecutionPolicyError,
    SpecialistExecutorRegistry,
    StaticProposalSpecialistExecutor,
)


def _executor(
    *,
    agent_id: str = "development.planner",
    agent_version: str = "1.0.0",
    output_contract: str = "simorgh.typed-plan.v1",
) -> StaticProposalSpecialistExecutor:
    return StaticProposalSpecialistExecutor(
        agent_id=agent_id,
        agent_version=agent_version,
        output_contract=output_contract,
        payload={"summary": "fixture"},
        wall_clock_millis=lambda: 1_000,
    )


@pytest.mark.parametrize(
    "executor, message",
    [
        (_executor(agent_id="Development Planner"), "agent_id is invalid"),
        (_executor(agent_id="development/planner"), "agent_id is invalid"),
        (_executor(agent_version="latest"), "version is invalid"),
        (_executor(output_contract="Invalid Contract"), "output contract is invalid"),
    ],
)
def test_registry_rejects_malformed_executor_identity(
    executor: StaticProposalSpecialistExecutor,
    message: str,
) -> None:
    with pytest.raises(SpecialistExecutionPolicyError, match=message):
        SpecialistExecutorRegistry((executor,))


def test_cancellation_is_idempotent_and_preserves_first_reason() -> None:
    token = SpecialistCancellation()

    token.cancel("اولین دلیل")
    token.cancel("دلیل دوم")
    token.cancel("")

    assert token.cancelled
    assert token.reason == "اولین دلیل"
