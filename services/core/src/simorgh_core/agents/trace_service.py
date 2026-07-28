from __future__ import annotations

import re
from uuid import UUID

from simorgh_core.agents.context_store import (
    ContextNotFoundError,
    ContextStore,
    ContextStoreError,
)
from simorgh_core.agents.invocations import (
    InvocationPhase,
    InvocationStore,
    InvocationStoreError,
)
from simorgh_core.agents.result_authority import (
    PrivacyClassification,
    RetentionDisposition,
)
from simorgh_core.agents.result_store import (
    ResultNotFoundError,
    ResultStore,
    ResultStoreError,
)
from simorgh_core.agents.task_store import AgentTaskStore, AgentTaskStoreError
from simorgh_core.agents.trace_authority import (
    TraceEventCandidate,
    TracePhase,
    TraceSafeMetadata,
    TraceUncertaintyDisposition,
)
from simorgh_core.agents.trace_store import TraceStore
from simorgh_core.agents.tracing import (
    CacheDisposition,
    TraceEvent,
    TraceEventKind,
    TraceSink,
)

_RESOURCE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._:/-][a-z0-9]+)*$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_PHASE_BY_KIND: dict[TraceEventKind, TracePhase] = {
    TraceEventKind.ROUTING_STARTED: TracePhase.ROUTING,
    TraceEventKind.ROUTING_COMPLETED: TracePhase.ROUTING,
    TraceEventKind.BUDGET_RESERVED: TracePhase.INVOCATION,
    TraceEventKind.BUDGET_RECONCILED: TracePhase.INVOCATION,
    TraceEventKind.INVOCATION_REPLAYED: TracePhase.INVOCATION,
    TraceEventKind.MODEL_STARTED: TracePhase.MODEL,
    TraceEventKind.MODEL_COMPLETED: TracePhase.MODEL,
    TraceEventKind.MODEL_FAILED: TracePhase.MODEL,
    TraceEventKind.TOOL_STARTED: TracePhase.TOOL,
    TraceEventKind.TOOL_COMPLETED: TracePhase.TOOL,
    TraceEventKind.TOOL_FAILED: TracePhase.TOOL,
    TraceEventKind.SPECIALIST_STARTED: TracePhase.SPECIALIST,
    TraceEventKind.SPECIALIST_COMPLETED: TracePhase.SPECIALIST,
    TraceEventKind.SPECIALIST_FAILED: TracePhase.SPECIALIST,
    TraceEventKind.RESULT_COMMITTED: TracePhase.RESULT,
    TraceEventKind.RESULT_REPLAYED: TracePhase.RESULT,
    TraceEventKind.RESULT_FAILED: TracePhase.RESULT,
    TraceEventKind.CANCELLATION_SETTLED: TracePhase.CANCELLATION,
    TraceEventKind.CANCELLATION_REPLAYED: TracePhase.CANCELLATION,
    TraceEventKind.CONTEXT_COMPILED: TracePhase.CONTEXT,
    TraceEventKind.CONTEXT_REPLAYED: TracePhase.CONTEXT,
    TraceEventKind.CONTEXT_FAILED: TracePhase.CONTEXT,
    TraceEventKind.ESCALATION: TracePhase.TERMINAL,
    TraceEventKind.TERMINAL: TracePhase.TERMINAL,
}
_COMPLETED_INVOCATION_KINDS = frozenset(
    {
        TraceEventKind.INVOCATION_REPLAYED,
        TraceEventKind.MODEL_COMPLETED,
        TraceEventKind.TOOL_COMPLETED,
        TraceEventKind.SPECIALIST_COMPLETED,
        TraceEventKind.RESULT_COMMITTED,
        TraceEventKind.RESULT_REPLAYED,
        TraceEventKind.RESULT_FAILED,
    }
)
_STARTED_INVOCATION_KINDS = frozenset(
    {
        TraceEventKind.MODEL_STARTED,
        TraceEventKind.TOOL_STARTED,
        TraceEventKind.SPECIALIST_STARTED,
        TraceEventKind.BUDGET_RESERVED,
        TraceEventKind.BUDGET_RECONCILED,
    }
)
_FAILED_INVOCATION_KINDS = frozenset(
    {
        TraceEventKind.MODEL_FAILED,
        TraceEventKind.TOOL_FAILED,
        TraceEventKind.SPECIALIST_FAILED,
    }
)


class TraceProjectionError(RuntimeError):
    """A legacy event could not be reduced to the durable privacy contract."""


class TraceCorrelationError(RuntimeError):
    """A trace candidate disagreed with its owning native authority."""


class TraceEventProjector:
    """Project process-local events into explicit non-content trace candidates."""

    def project(self, event: TraceEvent) -> TraceEventCandidate:
        metadata = event.metadata
        phase = _PHASE_BY_KIND[event.kind]
        outcome = _optional_resource(event.outcome, field="outcome")
        context_bundle_id = _optional_uuid(metadata, "context_bundle_id")
        result_id = _optional_uuid(metadata, "result_id")
        cancellation_id = _optional_uuid(metadata, "cancellation_id")
        connector_id = _optional_resource(
            _metadata_string(metadata, "connector_id"),
            field="connector identity",
        )
        privacy = _privacy(metadata)
        retention = _retention(metadata)
        tainted = _metadata_bool(metadata, "tainted", default=False)
        effect = _optional_resource(
            _metadata_string(metadata, "effect"),
            field="effect",
        )
        uncertainty = _uncertainty(outcome)
        operation_id = _optional_uuid(metadata, "operation_id")
        if operation_id is None:
            operation_id = _optional_uuid(metadata, "decision_id")
        if operation_id is None and phase == TracePhase.CANCELLATION:
            operation_id = event.event_id

        safe_metadata = TraceSafeMetadata(
            effect=effect,
            state_before=_optional_resource(
                _first_string(metadata, "state_before", "prior_state"),
                field="prior state",
            ),
            state_after=_optional_resource(
                _first_string(metadata, "state_after", "final_state"),
                field="final state",
            ),
            schema_id=_optional_resource(
                _first_string(
                    metadata,
                    "schema_id",
                    "result_schema_id",
                    "output_contract",
                ),
                field="schema identity",
            ),
            schema_version=_optional_version(
                _first_string(metadata, "schema_version", "result_schema_version")
            ),
            context_sha256=_optional_hash(metadata, "context_sha256"),
            result_sha256=(
                _optional_hash(metadata, "canonical_sha256")
                if phase == TracePhase.RESULT
                else _optional_hash(metadata, "result_sha256")
            ),
            projection_sha256=_optional_hash(metadata, "projection_sha256"),
            usage_snapshot_sha256=_first_hash(
                metadata,
                "usage_snapshot_sha256",
                "usage_sha256",
            ),
            ownership_snapshot_sha256=_optional_hash(
                metadata,
                "ownership_snapshot_sha256",
            ),
            source_reference_sha256=_first_hash(
                metadata,
                "source_reference_sha256",
                "source_manifest_sha256",
            ),
            section_count=_optional_int(metadata, "section_count"),
            item_count=_optional_int(metadata, "item_count"),
            byte_count=_first_int(metadata, "byte_count", "total_bytes", "response_bytes"),
            estimated_tokens=_first_int(
                metadata,
                "estimated_tokens",
                "estimated_unit_count",
            ),
            omission_count=_optional_int(metadata, "omission_count"),
            evidence_count=_optional_int(metadata, "evidence_count"),
            artifact_count=_optional_int(metadata, "artifact_count"),
            terminal_count=_optional_int(metadata, "terminal_count"),
            pending_count=_first_int(
                metadata,
                "pending_count",
                "pending_cancelled_count",
            ),
            reserved_count=_reserved_count(metadata),
            replayed=_optional_bool(metadata, "replayed"),
        )
        return TraceEventCandidate(
            request_id=event.request_id,
            occurred_at_ms=event.occurred_at_ms,
            kind=event.kind,
            phase=phase,
            operation_id=operation_id,
            invocation_id=event.invocation_id,
            parent_invocation_id=_optional_uuid(metadata, "parent_invocation_id"),
            context_bundle_id=context_bundle_id,
            result_id=result_id,
            evidence_id=_optional_uuid(metadata, "evidence_id"),
            cancellation_id=cancellation_id,
            agent_id=event.agent_id,
            agent_version=event.agent_version,
            routing_method=event.routing_method,
            rule_id=event.rule_id,
            provider_id=event.provider_id,
            model_id=event.model_id,
            tool_id=event.tool_id,
            connector_id=connector_id,
            cache=event.cache,
            usage_delta=event.usage,
            outcome=outcome,
            reason_code=(
                _optional_resource(
                    _metadata_string(metadata, "reason_code"),
                    field="reason code",
                )
                or outcome
            ),
            uncertainty=uncertainty,
            privacy=privacy,
            retention=retention,
            tainted=tainted,
            metadata=safe_metadata,
        )


class NativeTraceCorrelationValidator:
    """Cross-check trace metadata against the stores that own each transition."""

    def __init__(
        self,
        *,
        task_store: AgentTaskStore,
        invocation_store: InvocationStore,
        context_store: ContextStore,
        result_store: ResultStore,
    ) -> None:
        self._tasks = task_store
        self._invocations = invocation_store
        self._contexts = context_store
        self._results = result_store

    def validate(self, candidate: TraceEventCandidate) -> None:
        try:
            task_entry = self._tasks.get(candidate.request_id)
        except AgentTaskStoreError:
            raise TraceCorrelationError("trace task authority is unavailable") from None
        if task_entry is None:
            raise TraceCorrelationError("trace request has no durable task authority")

        if candidate.kind == TraceEventKind.ROUTING_COMPLETED:
            decision = task_entry.record.routing_decision
            if decision is None:
                raise TraceCorrelationError("routing trace has no durable decision")
            if candidate.operation_id is not None and candidate.operation_id != decision.decision_id:
                raise TraceCorrelationError("routing trace decision identity conflicts")
            if candidate.agent_id != decision.selected_agent_id:
                raise TraceCorrelationError("routing trace agent identity conflicts")
            if candidate.agent_version != decision.selected_agent_version:
                raise TraceCorrelationError("routing trace agent version conflicts")
            if candidate.routing_method != decision.method:
                raise TraceCorrelationError("routing trace method conflicts")
            if candidate.rule_id is not None and candidate.rule_id not in decision.matched_rule_ids:
                raise TraceCorrelationError("routing trace rule identity conflicts")

        if candidate.phase in {
            TracePhase.INVOCATION,
            TracePhase.SPECIALIST,
            TracePhase.MODEL,
            TracePhase.TOOL,
            TracePhase.RESULT,
        }:
            self._validate_invocation(candidate)

        if candidate.context_bundle_id is not None:
            self._validate_context(candidate)
        elif candidate.kind in {
            TraceEventKind.CONTEXT_COMPILED,
            TraceEventKind.CONTEXT_REPLAYED,
        }:
            raise TraceCorrelationError("completed context trace lacks context identity")

        if candidate.result_id is not None:
            self._validate_result(candidate)
        elif candidate.kind in {
            TraceEventKind.RESULT_COMMITTED,
            TraceEventKind.RESULT_REPLAYED,
        }:
            raise TraceCorrelationError("completed result trace lacks result identity")

        if candidate.cancellation_id is not None:
            cancellation = task_entry.record.cancellation_request
            if cancellation is None or cancellation.cancellation_id != candidate.cancellation_id:
                raise TraceCorrelationError("cancellation trace identity conflicts")
            result = task_entry.record.cancellation_result
            expected_hash = candidate.metadata.ownership_snapshot_sha256
            if expected_hash is not None:
                if result is None or result.ownership_snapshot_sha256 != expected_hash:
                    raise TraceCorrelationError(
                        "cancellation ownership snapshot conflicts"
                    )

    def _validate_invocation(self, candidate: TraceEventCandidate) -> None:
        if candidate.invocation_id is None:
            raise TraceCorrelationError("trace phase lacks invocation identity")
        try:
            invocation = self._invocations.get(candidate.invocation_id)
        except InvocationStoreError:
            raise TraceCorrelationError("trace invocation authority is unavailable") from None
        if invocation.request_id != candidate.request_id:
            raise TraceCorrelationError("trace invocation belongs to another request")
        if (
            candidate.parent_invocation_id is not None
            and candidate.parent_invocation_id != invocation.parent_invocation_id
        ):
            raise TraceCorrelationError("trace invocation parent conflicts")
        if candidate.agent_id is not None and candidate.agent_id != invocation.agent_id:
            raise TraceCorrelationError("trace invocation agent identity conflicts")
        if (
            candidate.agent_version is not None
            and candidate.agent_version != invocation.agent_version
        ):
            raise TraceCorrelationError("trace invocation agent version conflicts")
        if candidate.provider_id is not None and candidate.provider_id != invocation.provider_id:
            raise TraceCorrelationError("trace provider identity conflicts")
        if candidate.model_id is not None and candidate.model_id != invocation.model_id:
            raise TraceCorrelationError("trace model identity conflicts")
        if candidate.tool_id is not None and candidate.tool_id != invocation.tool_id:
            raise TraceCorrelationError("trace tool identity conflicts")
        if candidate.connector_id is not None and candidate.connector_id != invocation.connector_id:
            raise TraceCorrelationError("trace connector identity conflicts")
        if candidate.metadata.effect is not None and candidate.metadata.effect != invocation.effect.value:
            raise TraceCorrelationError("trace invocation effect conflicts")

        if candidate.kind in _COMPLETED_INVOCATION_KINDS:
            if invocation.state != InvocationPhase.COMPLETED:
                raise TraceCorrelationError("completion trace contradicts invocation state")
            if candidate.usage_delta != invocation.committed_usage:
                raise TraceCorrelationError("completion trace usage conflicts")
        elif candidate.kind in _STARTED_INVOCATION_KINDS:
            if invocation.state != InvocationPhase.RESERVED:
                raise TraceCorrelationError("start trace contradicts invocation state")
            if (
                candidate.kind == TraceEventKind.BUDGET_RESERVED
                and candidate.usage_delta != invocation.reserved_usage
            ):
                raise TraceCorrelationError("reservation trace usage conflicts")
        elif candidate.kind in _FAILED_INVOCATION_KINDS:
            if not invocation.terminal or invocation.state == InvocationPhase.COMPLETED:
                raise TraceCorrelationError("failure trace contradicts invocation state")
            if (
                candidate.usage_delta != invocation.committed_usage
                and candidate.usage_delta.model_dump() != {}
            ):
                zero = candidate.usage_delta.__class__()
                if candidate.usage_delta != zero:
                    raise TraceCorrelationError("failure trace usage conflicts")

    def _validate_context(self, candidate: TraceEventCandidate) -> None:
        assert candidate.context_bundle_id is not None
        try:
            context = self._contexts.get(candidate.context_bundle_id)
        except (ContextNotFoundError, ContextStoreError):
            raise TraceCorrelationError("trace context authority is unavailable") from None
        if context.request_id != candidate.request_id:
            raise TraceCorrelationError("trace context belongs to another request")
        if (
            candidate.invocation_id is not None
            and context.specialist_invocation_id != candidate.invocation_id
        ):
            raise TraceCorrelationError("trace context invocation conflicts")
        if candidate.agent_id is not None and context.agent_id != candidate.agent_id:
            raise TraceCorrelationError("trace context agent identity conflicts")
        if candidate.agent_version is not None and context.agent_version != candidate.agent_version:
            raise TraceCorrelationError("trace context agent version conflicts")
        if (
            candidate.metadata.context_sha256 is not None
            and context.canonical_sha256 != candidate.metadata.context_sha256
        ):
            raise TraceCorrelationError("trace context hash conflicts")
        if candidate.privacy != context.privacy or candidate.retention != context.retention:
            raise TraceCorrelationError("trace context classification conflicts")
        if candidate.tainted != context.tainted:
            raise TraceCorrelationError("trace context taint conflicts")

    def _validate_result(self, candidate: TraceEventCandidate) -> None:
        assert candidate.result_id is not None
        try:
            result = self._results.get(candidate.result_id)
        except (ResultNotFoundError, ResultStoreError):
            raise TraceCorrelationError("trace result authority is unavailable") from None
        if result.request_id != candidate.request_id:
            raise TraceCorrelationError("trace result belongs to another request")
        if candidate.invocation_id is not None and result.invocation_id != candidate.invocation_id:
            raise TraceCorrelationError("trace result invocation conflicts")
        if candidate.agent_id is not None and result.producer_agent_id != candidate.agent_id:
            raise TraceCorrelationError("trace result producer conflicts")
        if (
            candidate.agent_version is not None
            and result.producer_agent_version != candidate.agent_version
        ):
            raise TraceCorrelationError("trace result producer version conflicts")
        if (
            candidate.metadata.result_sha256 is not None
            and result.canonical_sha256 != candidate.metadata.result_sha256
        ):
            raise TraceCorrelationError("trace result hash conflicts")
        if candidate.privacy != result.privacy or candidate.retention != result.retention:
            raise TraceCorrelationError("trace result classification conflicts")


class DurableTraceSink(TraceSink):
    """Fail-closed bridge from existing emitters to correlated trace authority."""

    def __init__(
        self,
        *,
        store: TraceStore,
        validator: NativeTraceCorrelationValidator,
        projector: TraceEventProjector | None = None,
    ) -> None:
        self._store = store
        self._validator = validator
        self._projector = projector or TraceEventProjector()

    def emit(self, event: TraceEvent) -> None:
        candidate = self._projector.project(event)
        self._validator.validate(candidate)
        self._store.append(candidate)


def _uncertainty(outcome: str | None) -> TraceUncertaintyDisposition:
    if outcome == TraceUncertaintyDisposition.UNKNOWN_SIDE_EFFECT.value:
        return TraceUncertaintyDisposition.UNKNOWN_SIDE_EFFECT
    if outcome == TraceUncertaintyDisposition.UNKNOWN.value:
        return TraceUncertaintyDisposition.UNKNOWN
    return TraceUncertaintyDisposition.NONE


def _privacy(metadata: dict[str, str | int | bool | None]) -> PrivacyClassification:
    value = _metadata_string(metadata, "privacy")
    if value is None:
        return PrivacyClassification.INTERNAL
    try:
        return PrivacyClassification(value)
    except ValueError:
        raise TraceProjectionError("trace privacy classification is invalid") from None


def _retention(metadata: dict[str, str | int | bool | None]) -> RetentionDisposition:
    value = _metadata_string(metadata, "retention")
    if value is None:
        return RetentionDisposition.PROJECT
    try:
        return RetentionDisposition(value)
    except ValueError:
        raise TraceProjectionError("trace retention disposition is invalid") from None


def _optional_uuid(
    metadata: dict[str, str | int | bool | None],
    key: str,
) -> UUID | None:
    value = metadata.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TraceProjectionError("trace correlation identity has invalid type")
    try:
        return UUID(value)
    except ValueError:
        raise TraceProjectionError("trace correlation identity is invalid") from None


def _metadata_string(
    metadata: dict[str, str | int | bool | None],
    key: str,
) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TraceProjectionError("trace metadata identifier has invalid type")
    if not value or "\n" in value or "\r" in value:
        raise TraceProjectionError("trace metadata identifier is invalid")
    return value


def _first_string(
    metadata: dict[str, str | int | bool | None],
    *keys: str,
) -> str | None:
    for key in keys:
        value = _metadata_string(metadata, key)
        if value is not None:
            return value
    return None


def _optional_resource(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    if len(value) > 128 or _RESOURCE_ID.fullmatch(value) is None:
        raise TraceProjectionError(f"trace {field} is not a bounded resource identity")
    return value


def _optional_version(value: str | None) -> str | None:
    if value is None:
        return None
    if re.fullmatch(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?$", value) is None:
        raise TraceProjectionError("trace schema version is invalid")
    return value


def _optional_hash(
    metadata: dict[str, str | int | bool | None],
    key: str,
) -> str | None:
    value = _metadata_string(metadata, key)
    if value is None:
        return None
    if _HASH.fullmatch(value) is None:
        raise TraceProjectionError("trace hash metadata is invalid")
    return value


def _first_hash(
    metadata: dict[str, str | int | bool | None],
    *keys: str,
) -> str | None:
    for key in keys:
        value = _optional_hash(metadata, key)
        if value is not None:
            return value
    return None


def _optional_int(
    metadata: dict[str, str | int | bool | None],
    key: str,
) -> int | None:
    value = metadata.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TraceProjectionError("trace count metadata is invalid")
    return value


def _first_int(
    metadata: dict[str, str | int | bool | None],
    *keys: str,
) -> int | None:
    for key in keys:
        value = _optional_int(metadata, key)
        if value is not None:
            return value
    return None


def _optional_bool(
    metadata: dict[str, str | int | bool | None],
    key: str,
) -> bool | None:
    value = metadata.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise TraceProjectionError("trace boolean metadata is invalid")
    return value


def _metadata_bool(
    metadata: dict[str, str | int | bool | None],
    key: str,
    *,
    default: bool,
) -> bool:
    value = _optional_bool(metadata, key)
    return default if value is None else value


def _reserved_count(metadata: dict[str, str | int | bool | None]) -> int | None:
    direct = _optional_int(metadata, "reserved_count")
    if direct is not None:
        return direct
    cancelled = _optional_int(metadata, "reserved_cancelled_count")
    uncertain = _optional_int(metadata, "reserved_uncertain_count")
    if cancelled is None and uncertain is None:
        return None
    return (cancelled or 0) + (uncertain or 0)


__all__ = [
    "DurableTraceSink",
    "NativeTraceCorrelationValidator",
    "TraceCorrelationError",
    "TraceEventProjector",
    "TraceProjectionError",
]
