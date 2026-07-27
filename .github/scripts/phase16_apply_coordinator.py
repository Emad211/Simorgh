from __future__ import annotations

import textwrap
from pathlib import Path

SOURCE = Path(".github/workflows/phase16-cancellation-coordinator.yml")
CONTROL_PLANE = Path("services/core/src/simorgh_core/agents/control_plane.py")
START_MARKER = "          python - <<'PY'\n"
END_MARKER = "\n          PY\n"

CANCEL_METHOD = textwrap.dedent(
    '''\
async def cancel(
    self,
    *,
    request_id: UUID,
    reason: str,
    cancellation_id: UUID | None = None,
    reason_code: str = "operator_requested",
    requester_authority: CancellationRequesterAuthority = (
        CancellationRequesterAuthority.OPERATOR
    ),
) -> AgentTaskRecord:
    normalized_reason = " ".join(reason.strip().split())[:1_000]
    if not normalized_reason:
        normalized_reason = "operator requested cancellation"

    with self._lock:
        self._require_store_healthy_locked()
        state = self._states.get(request_id)
        if state is None:
            raise AgentTaskNotFoundError(f"agent task {request_id} was not found")
        if state.record.phase == AgentTaskPhase.EXPIRED:
            return state.record

        existing_request = state.record.cancellation_request
        if existing_request is not None:
            candidate_id = cancellation_id or existing_request.cancellation_id
            candidate = existing_request.model_copy(
                update={
                    "cancellation_id": candidate_id,
                    "reason_code": reason_code,
                    "operator_reason": normalized_reason,
                    "requester_authority": requester_authority,
                }
            )
            if candidate != existing_request:
                raise AgentTaskConflictError(
                    "cancellation identity was replayed with different content"
                )
            cancellation_request = existing_request
            if state.record.cancellation_result is not None:
                return state.record
        else:
            now = self._now_ms()
            resolved_id = cancellation_id or stable_cancellation_id(
                request_id=request_id,
                reason_code=reason_code,
                operator_reason=normalized_reason,
                requester_authority=requester_authority,
            )
            cancellation_request = TaskCancellationRequest(
                request_id=request_id,
                cancellation_id=resolved_id,
                requested_at_ms=now,
                reason_code=reason_code,
                operator_reason=normalized_reason,
                requester_authority=requester_authority,
                observed_task_phase=state.record.phase.value,
                observed_task_version=state.record.updated_at_ms,
            )
            state.cancelled = True
            state.cancel_reason = normalized_reason
            state.account.cancel()
            accepted_record = AgentTaskRecord(
                request_id=request_id,
                phase=AgentTaskPhase.CANCELLED,
                created_at_ms=state.record.created_at_ms,
                updated_at_ms=self._next_record_time(state.record.updated_at_ms),
                task=state.task,
                routing_decision=state.record.routing_decision,
                budget=state.account.snapshot(),
                cancel_reason=state.cancel_reason,
                cancellation_request=cancellation_request,
                detail=state.cancel_reason,
            )
            self._persist_transition_locked(
                state=state,
                account=state.account,
                record=accepted_record,
            )

    fence = self._invocations.accept_cancellation(cancellation_request)
    signal_dispositions = self._cancellation_owners.signal_request(
        request_id=request_id,
        reason=normalized_reason,
    )
    settled = self._invocations.settle_cancellation(request_id)
    settled_by_id = {record.invocation_id: record for record in settled}

    outcomes: list[InvocationCancellationOutcome] = []
    terminal_count = 0
    pending_cancelled_count = 0
    reserved_uncertain_count = 0
    signalled_count = 0
    signalled_owner_ids: set[UUID] = set()

    for owned in fence.owned_invocations:
        final = settled_by_id[owned.invocation_id]
        if owned.cancellation_owner_id is None:
            signal = CancellationSignalDisposition.NOT_REGISTERED
        elif owned.cancellation_owner_id in signalled_owner_ids:
            signal = CancellationSignalDisposition.ALREADY_SIGNALLED
        else:
            raw_signal = signal_dispositions.get(
                owned.cancellation_owner_id,
                CancellationSignalDisposition.NOT_REGISTERED,
            )
            if raw_signal in {
                CancellationSignalDisposition.SIGNALLED,
                CancellationSignalDisposition.ALREADY_SIGNALLED,
            }:
                signal = CancellationSignalDisposition.SIGNALLED
                signalled_owner_ids.add(owned.cancellation_owner_id)
                signalled_count += 1
            else:
                signal = raw_signal

        if owned.terminal:
            terminal_count += 1
            adapter = AdapterCancellationDisposition.ALREADY_TERMINAL
        elif owned.state == InvocationPhase.PENDING.value:
            pending_cancelled_count += 1
            adapter = AdapterCancellationDisposition.PROVEN_NOT_ENTERED
        else:
            reserved_uncertain_count += 1
            adapter = AdapterCancellationDisposition.NOT_SUPPORTED

        outcomes.append(
            InvocationCancellationOutcome(
                invocation_id=owned.invocation_id,
                prior_state=owned.state,
                final_state=final.state.value,
                signal_disposition=signal,
                adapter_disposition=adapter,
                usage_sha256=canonical_fingerprint(final.committed_usage),
            )
        )

    if reserved_uncertain_count:
        disposition = CancellationDisposition.PARTIALLY_UNCERTAIN
    elif outcomes and terminal_count == len(outcomes):
        disposition = CancellationDisposition.OBSERVED_TERMINAL
    else:
        disposition = CancellationDisposition.APPLIED

    result = TaskCancellationResult(
        request=cancellation_request,
        accepted_at_ms=fence.accepted_at_ms,
        completed_at_ms=max(fence.accepted_at_ms, self._now_ms()),
        ownership_snapshot_sha256=fence.ownership_snapshot_sha256,
        outcomes=tuple(outcomes),
        terminal_count=terminal_count,
        pending_cancelled_count=pending_cancelled_count,
        reserved_uncertain_count=reserved_uncertain_count,
        signalled_count=signalled_count,
        disposition=disposition,
        audit_event_id=stable_cancellation_audit_id(
            request_id=request_id,
            cancellation_id=cancellation_request.cancellation_id,
            ownership_snapshot_sha256=fence.ownership_snapshot_sha256,
        ),
    )

    with self._lock:
        self._require_store_healthy_locked()
        state = self._states[request_id]
        if state.record.cancellation_result is not None:
            return state.record
        completed_record = state.record.model_copy(
            update={
                "updated_at_ms": self._next_record_time(
                    state.record.updated_at_ms
                ),
                "cancellation_result": result,
                "detail": "durable cancellation propagation completed",
            }
        )
        self._persist_transition_locked(
            state=state,
            account=state.account,
            record=completed_record,
        )
        return completed_record
'''
)


def replace_exact(
    text: str,
    old: str,
    new: str,
    *,
    label: str,
    expected: int = 1,
) -> str:
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: count={count}, expected={expected}")
    return text.replace(old, new)


def extract_embedded_source() -> str:
    source = SOURCE.read_text(encoding="utf-8")
    if source.count(START_MARKER) != 1:
        raise SystemExit("coordinator source start marker is not unique")
    remainder = source.split(START_MARKER, 1)[1]
    if remainder.count(END_MARKER) != 1:
        raise SystemExit("coordinator source end marker is not unique")
    raw = remainder.split(END_MARKER, 1)[0]
    return "\n".join(
        line[10:] if line.startswith("          ") else line
        for line in raw.splitlines()
    )


def harden_embedded_source(embedded: str) -> str:
    embedded = replace_exact(
        embedded,
        '"             previous_store.close()\\n',
        '"            previous_store.close()\\n',
        label="reset anchor indentation",
        expected=2,
    )
    embedded = replace_exact(
        embedded,
        "        input_fingerprint=(kind.value[0] * 64),",
        '        input_fingerprint=({\\n'
        '            InvocationKind.MODEL: "a",\\n'
        '            InvocationKind.TOOL: "b",\\n'
        '            InvocationKind.SPECIALIST: "c",\\n'
        '        }[kind] * 64),',
        label="test fingerprint alphabet",
    )

    api_start = embedded.index(
        'api = "services/core/src/simorgh_core/agents/api.py"'
    )
    app_start = embedded.index(
        'app = "services/core/src/simorgh_core/app.py"'
    )
    api_segment = embedded[api_start:app_start]
    api_segment = replace_exact(
        api_segment,
        "expected=1",
        "expected=2",
        label="API conflict mapping cardinality",
    )
    embedded = embedded[:api_start] + api_segment + embedded[app_start:]

    tool_start = embedded.index(
        'tool_gateway = "services/core/src/simorgh_core/agents/tool_gateway.py"'
    )
    github_start = embedded.index(
        'github_service = "services/core/src/simorgh_core/agents/github_read_service.py"'
    )
    tool_segment = embedded[tool_start:github_start]
    connector_literal = '"                connector_id=request.connector_id,\\n"'
    narrowed_literal = (
        '"                effect=InvocationEffect.READ_ONLY,\\n"\n'
        '    "                tool_id=request.tool_id,\\n"\n'
        '    "                connector_id=request.connector_id,\\n"'
    )
    tool_segment = replace_exact(
        tool_segment,
        connector_literal,
        narrowed_literal,
        label="tool gateway owner patch literals",
        expected=2,
    )
    embedded = embedded[:tool_start] + tool_segment + embedded[github_start:]

    model_start = embedded.index(
        'model_gateway = "services/core/src/simorgh_core/agents/model_gateway.py"'
    )
    github_segment = embedded[github_start:model_start]
    github_segment = replace_exact(
        github_segment,
        "task.allowed_data_sources",
        "request.allowed_data_sources",
        label="GitHub read effective data-source anchor",
        expected=2,
    )
    embedded = embedded[:github_start] + github_segment + embedded[model_start:]

    return replace_exact(
        embedded,
        "replace_count(start, old_cancel, new_cancel)",
        "pass  # cancellation method is patched by the outer gate",
        label="disable malformed embedded cancellation replacement",
    )


def patch_control_plane_cancel() -> None:
    text = CONTROL_PLANE.read_text(encoding="utf-8")
    start = text.index("    async def cancel(\n")
    end = text.index("    async def clear_for_test", start)
    replacement = textwrap.indent(CANCEL_METHOD.rstrip(), "    ") + "\n\n"
    CONTROL_PLANE.write_text(
        text[:start] + replacement + text[end:],
        encoding="utf-8",
    )


def main() -> None:
    embedded = harden_embedded_source(extract_embedded_source())
    exec(
        compile(embedded, "phase16-coordinator.py", "exec"),
        {"__name__": "__main__"},
    )
    patch_control_plane_cancel()
    print("coordinator_patch_complete=true")


if __name__ == "__main__":
    main()
