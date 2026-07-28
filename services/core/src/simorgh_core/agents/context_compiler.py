from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from simorgh_core.agents.context_contracts import (
    ContextBudgetProjection,
    ContextCompilationRequest,
    ContextCompilerPolicy,
    ContextMaterial,
    ContextOmission,
    ContextOmissionReason,
    ContextReplayDisposition,
    ContextSection,
    ContextSectionDisposition,
    ContextSourceKind,
    ContextToolSchemaProjection,
    ContextTrustClass,
    SpecialistContextBundle,
    context_bundle_canonical_payload,
    context_bundle_canonical_sha256,
    context_bundle_id_for,
    context_material_id_for,
    context_omission_sort_key,
    context_remaining_usage,
    context_section_from_material,
    context_section_sort_key,
    context_source_manifest_sha256,
    context_text_sha256,
    estimate_context_tokens,
)
from simorgh_core.agents.context_projections import build_context_output_schema
from simorgh_core.agents.context_sources import ContextMaterialRegistry
from simorgh_core.agents.context_store import ContextClaimKind, ContextStore
from simorgh_core.agents.contracts import (
    ExecutionMode,
    FreshnessClass,
    RoutingDecision,
    RoutingState,
    SideEffectPolicy,
    SpecialistDefinition,
    TaskBudget,
)
from simorgh_core.agents.invocations import (
    InvocationEffect,
    InvocationStore,
    canonical_fingerprint,
    canonical_json,
    canonical_size_bytes,
)
from simorgh_core.agents.registry import SpecialistRegistry, intersect_budgets
from simorgh_core.agents.result_authority import (
    EvidenceCacheDisposition,
    PrivacyClassification,
    ResultSchemaRegistry,
    RetentionDisposition,
    strictest_privacy,
    strictest_retention,
)
from simorgh_core.agents.specialist_execution import SpecialistCapabilitySet
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import AgentTaskStore
from simorgh_core.agents.tracing import (
    CacheDisposition,
    NullTraceSink,
    TraceEventKind,
    TraceSink,
    trace_event,
)


class ContextCompilerError(RuntimeError):
    """Base class for deterministic context compiler failures."""


class ContextCompilerDisabledError(ContextCompilerError):
    pass


class ContextCompilerPolicyError(ContextCompilerError):
    pass


class ContextCompilerFreshnessError(ContextCompilerError):
    pass


class ContextCompilerLimitError(ContextCompilerError):
    pass


class ContextCompilerCancelledError(ContextCompilerError):
    pass


class ContextCompilationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    bundle: SpecialistContextBundle
    replayed: bool


@dataclass(frozen=True)
class _Authority:
    record: AgentTaskRecord
    decision: RoutingDecision
    definition: SpecialistDefinition
    effective_budget: TaskBudget
    task_fingerprint: str
    routing_fingerprint: str
    policy_fingerprint: str
    budget: ContextBudgetProjection


class ContextCompilerService:
    """Compile and durably claim one zero-external specialist context bundle."""

    def __init__(
        self,
        *,
        task_store: AgentTaskStore,
        invocation_store: InvocationStore,
        specialist_registry: SpecialistRegistry,
        result_schema_registry: ResultSchemaRegistry,
        context_store: ContextStore,
        material_registry: ContextMaterialRegistry | None = None,
        reviewed_tool_schemas: Mapping[str, ContextToolSchemaProjection],
        policy: ContextCompilerPolicy | None = None,
        trace_sink: TraceSink | None = None,
        wall_clock_millis: Callable[[], int] | None = None,
    ) -> None:
        self._task_store = task_store
        self._invocations = invocation_store
        self._specialists = specialist_registry
        self._results = result_schema_registry
        self._contexts = context_store
        self._materials = material_registry or ContextMaterialRegistry()
        self._tool_schemas = dict(reviewed_tool_schemas)
        self._policy = policy or ContextCompilerPolicy()
        self._trace_sink = trace_sink or NullTraceSink()
        self._wall_clock_millis = wall_clock_millis or (
            lambda: int(time.time() * 1_000)
        )

    def compile(self, request: ContextCompilationRequest) -> ContextCompilationResult:
        try:
            result = self._compile(request)
        except Exception as exc:
            self._emit_failure(request=request, failure=exc)
            raise
        self._emit_result(result)
        return result

    def _compile(self, request: ContextCompilationRequest) -> ContextCompilationResult:
        if not self._policy.enabled:
            raise ContextCompilerDisabledError("context compiler is disabled")
        now_ms = self._now_ms()
        authority = self._require_authority(request=request, now_ms=now_ms)
        materials = self._prepare_materials(
            record=authority.record,
            task_fingerprint=authority.task_fingerprint,
            request=request,
        )
        sections, omissions = self._admit_materials(
            materials=materials,
            freshness=authority.record.task.freshness,
            now_ms=now_ms,
        )
        bundle = self._compact_and_build(
            authority=authority,
            request=request,
            sections=sections,
            omissions=omissions,
            compiled_at_ms=now_ms,
        )
        self._require_still_active(request.request_id, now_ms=now_ms)
        claim = self._contexts.claim(bundle)
        self._require_still_active(request.request_id, now_ms=self._now_ms())
        return ContextCompilationResult(
            bundle=claim.record,
            replayed=claim.kind == ContextClaimKind.REPLAY,
        )

    def _require_authority(
        self,
        *,
        request: ContextCompilationRequest,
        now_ms: int,
    ) -> _Authority:
        entry = self._task_store.get(request.request_id)
        if entry is None:
            raise ContextCompilerPolicyError("context task does not exist")
        record = entry.record
        if record.phase == AgentTaskPhase.CANCELLED or record.budget.cancelled:
            raise ContextCompilerCancelledError("cancelled task cannot compile context")
        if record.phase == AgentTaskPhase.EXPIRED:
            raise ContextCompilerCancelledError("expired task cannot compile context")
        if record.phase != AgentTaskPhase.ROUTED:
            raise ContextCompilerPolicyError("only a routed task can compile context")
        if record.budget.exhausted_dimension is not None:
            raise ContextCompilerPolicyError("exhausted task cannot compile context")
        if (
            record.task.deadline_at_ms is not None
            and now_ms >= record.task.deadline_at_ms
        ):
            raise ContextCompilerCancelledError("task deadline expired before compilation")
        if self._invocations.get_cancellation_fence(request.request_id) is not None:
            raise ContextCompilerCancelledError(
                "task cancellation fence blocks context compilation"
            )
        decision = record.routing_decision
        if decision is None or decision.state != RoutingState.ROUTED:
            raise ContextCompilerPolicyError("context task has no routed specialist")
        if decision.request_id != request.request_id:
            raise ContextCompilerPolicyError("routing identity does not match context request")
        if (
            decision.selected_agent_id != request.agent_id
            or decision.selected_agent_version != request.agent_version
        ):
            raise ContextCompilerPolicyError(
                "context request specialist does not match routing authority"
            )
        definition = self._specialists.get(request.agent_id)
        if definition.version != request.agent_version:
            raise ContextCompilerPolicyError(
                "context specialist version does not match active policy"
            )
        task_kind = record.task.explicit_task_kind
        if task_kind is not None and task_kind not in definition.task_kinds:
            raise ContextCompilerPolicyError(
                "context task kind is outside specialist policy"
            )
        maximum = _maximum_capabilities(record=record, definition=definition)
        request.capabilities.require_subset_of(maximum)
        _require_effect_capability(record=record, definition=definition, request=request)
        self._require_tool_schemas(request=request, definition=definition)
        expected_output = build_context_output_schema(
            registry=self._results,
            output_contract=definition.output_contract,
        )
        if request.output_schema != expected_output:
            raise ContextCompilerPolicyError(
                "context output schema does not match registered result authority"
            )
        effective_budget = intersect_budgets(
            record.task.budget,
            definition.budget_ceiling,
        )
        task_payload = record.task.model_dump(mode="json")
        task_payload["allowed_data_sources"] = sorted(
            record.task.allowed_data_sources
        )
        task_fingerprint = canonical_fingerprint(task_payload)
        if task_fingerprint != entry.task_fingerprint:
            raise ContextCompilerPolicyError(
                "context task fingerprint does not match durable authority"
            )
        return _Authority(
            record=record,
            decision=decision,
            definition=definition,
            effective_budget=effective_budget,
            task_fingerprint=task_fingerprint,
            routing_fingerprint=canonical_fingerprint(decision),
            policy_fingerprint=_policy_fingerprint(
                definition=definition,
                capabilities=request.capabilities,
                task_record=record,
                compiler_policy=self._policy,
            ),
            budget=_context_budget_projection(
                record=record,
                effective_budget=effective_budget,
            ),
        )

    def _require_tool_schemas(
        self,
        *,
        request: ContextCompilationRequest,
        definition: SpecialistDefinition,
    ) -> None:
        requested_ids = set(request.capabilities.tool_ids)
        projected_ids = {item.tool_id for item in request.tool_schemas}
        if projected_ids != requested_ids:
            raise ContextCompilerPolicyError(
                "context tool schemas must exactly match requested tool capabilities"
            )
        if not requested_ids.issubset(definition.tool_allowlist):
            raise ContextCompilerPolicyError(
                "context tool schemas exceed specialist allowlist"
            )
        if len(request.tool_schemas) > self._policy.limits.max_tools:
            raise ContextCompilerLimitError("context tool count exceeds compiler policy")
        tool_schema_bytes = sum(canonical_size_bytes(item) for item in request.tool_schemas)
        if tool_schema_bytes > self._policy.limits.max_tool_schema_bytes:
            raise ContextCompilerLimitError(
                "context tool schemas exceed compiler byte policy"
            )
        for projection in request.tool_schemas:
            reviewed = self._tool_schemas.get(projection.tool_id)
            if reviewed is None or reviewed != projection:
                raise ContextCompilerPolicyError(
                    "context tool schema is not the exact reviewed projection"
                )
            if (
                projection.connector_id is not None
                and projection.connector_id not in request.capabilities.connector_ids
            ):
                raise ContextCompilerPolicyError(
                    "context tool connector is outside requested capability subset"
                )
            if (
                projection.effect == InvocationEffect.MUTATION
                and not request.capabilities.typed_mutation_allowed
            ):
                raise ContextCompilerPolicyError(
                    "mutation tool schema requires typed mutation capability"
                )

    def _prepare_materials(
        self,
        *,
        record: AgentTaskRecord,
        task_fingerprint: str,
        request: ContextCompilationRequest,
    ) -> tuple[ContextMaterial, ...]:
        if any(item.source_kind == ContextSourceKind.USER_TASK for item in request.materials):
            raise ContextCompilerPolicyError(
                "caller cannot replace the compiler-owned user task section"
            )
        user_content = canonical_json(
            {
                "input_text": record.task.input_text,
                "requested_outcome": record.task.requested_outcome,
            }
        )
        user_source_sha = canonical_fingerprint(
            {
                "request_id": str(record.request_id),
                "task_fingerprint": task_fingerprint,
            }
        )
        user_material = ContextMaterial(
            material_id=context_material_id_for(
                request_id=record.request_id,
                source_kind=ContextSourceKind.USER_TASK,
                source_id="task.user-content",
                source_sha256=user_source_sha,
            ),
            request_id=record.request_id,
            source_kind=ContextSourceKind.USER_TASK,
            trust=ContextTrustClass.UNTRUSTED_USER_CONTENT,
            source_id="task.user-content",
            source_sha256=user_source_sha,
            content_sha256=context_text_sha256(user_content),
            content=user_content,
            required=True,
            priority=1_000,
            observed_at_ms=record.task.received_at_ms,
            cache_disposition=EvidenceCacheDisposition.LIVE,
            content_addressed=True,
            tainted=True,
            privacy=PrivacyClassification.INTERNAL,
            retention=RetentionDisposition.SESSION,
        )
        approved = tuple(
            self._materials.require(material) for material in request.materials
        )
        if any(material.request_id != record.request_id for material in approved):
            raise ContextCompilerPolicyError(
                "context material does not belong to task"
            )
        materials = (user_material, *approved)
        material_ids = [item.material_id for item in materials]
        if len(set(material_ids)) != len(material_ids):
            raise ContextCompilerPolicyError("context material identity conflicts")
        return tuple(materials)

    def _admit_materials(
        self,
        *,
        materials: tuple[ContextMaterial, ...],
        freshness: FreshnessClass,
        now_ms: int,
    ) -> tuple[list[ContextSection], list[ContextOmission]]:
        sections: list[ContextSection] = []
        omissions: list[ContextOmission] = []
        evidence_count = 0
        project_count = 0
        decision_count = 0
        ordered = sorted(materials, key=_material_sort_key)
        for material in ordered:
            reason = self._material_rejection_reason(
                material=material,
                freshness=freshness,
                now_ms=now_ms,
            )
            if reason is not None:
                if material.required:
                    if reason in {
                        ContextOmissionReason.STALE,
                        ContextOmissionReason.UNKNOWN_FRESHNESS,
                    }:
                        raise ContextCompilerFreshnessError(
                            "required context material is not fresh enough"
                        )
                    raise ContextCompilerPolicyError(
                        "required context material exceeds compiler policy"
                    )
                _append_report_once(omissions, _omission(material, reason))
                continue
            if len(sections) >= self._policy.limits.max_sections:
                if material.required:
                    raise ContextCompilerLimitError(
                        "required context material exceeds section limit"
                    )
                _append_report_once(
                    omissions,
                    _omission(material, ContextOmissionReason.SECTION_LIMIT),
                )
                continue
            if material.source_kind == ContextSourceKind.PROJECT_GOAL:
                if project_count >= self._policy.limits.max_project_items:
                    if material.required:
                        raise ContextCompilerLimitError(
                            "required project context exceeds project item limit"
                        )
                    _append_report_once(
                        omissions,
                        _omission(material, ContextOmissionReason.PROJECT_LIMIT),
                    )
                    continue
                project_count += 1
            elif material.source_kind == ContextSourceKind.DECISION:
                if decision_count >= self._policy.limits.max_decision_items:
                    if material.required:
                        raise ContextCompilerLimitError(
                            "required decision context exceeds decision item limit"
                        )
                    _append_report_once(
                        omissions,
                        _omission(material, ContextOmissionReason.DECISION_LIMIT),
                    )
                    continue
                decision_count += 1
            elif material.source_kind == ContextSourceKind.EVIDENCE:
                if evidence_count >= self._policy.limits.max_evidence_items:
                    if material.required:
                        raise ContextCompilerLimitError(
                            "required evidence exceeds evidence item limit"
                        )
                    _append_report_once(
                        omissions,
                        _omission(material, ContextOmissionReason.EVIDENCE_LIMIT),
                    )
                    continue
                evidence_count += 1
            if len(material.content) > self._policy.limits.max_text_characters:
                if material.required:
                    raise ContextCompilerLimitError(
                        "required context material exceeds text limit"
                    )
                included = material.content[
                    : self._policy.limits.max_text_characters
                ]
                sections.append(context_section_from_material(material, content=included))
                _append_report_once(
                    omissions,
                    _omission(material, ContextOmissionReason.TEXT_LIMIT),
                )
                continue
            sections.append(context_section_from_material(material))
        if len(omissions) > self._policy.limits.max_omissions:
            raise ContextCompilerLimitError("context omission report exceeds limit")
        return sections, omissions

    def _material_rejection_reason(
        self,
        *,
        material: ContextMaterial,
        freshness: FreshnessClass,
        now_ms: int,
    ) -> ContextOmissionReason | None:
        if _privacy_rank(material.privacy) > _privacy_rank(
            self._policy.privacy_ceiling
        ):
            return ContextOmissionReason.PRIVACY_CEILING
        if _retention_rank(material.retention) > _retention_rank(
            self._policy.retention_ceiling
        ):
            return ContextOmissionReason.RETENTION_CEILING
        if material.content_addressed:
            return None
        if material.fresh_until_ms is None:
            if freshness == FreshnessClass.CACHED_OK:
                return None
            return ContextOmissionReason.UNKNOWN_FRESHNESS
        if material.fresh_until_ms < now_ms:
            return ContextOmissionReason.STALE
        return None

    def _compact_and_build(
        self,
        *,
        authority: _Authority,
        request: ContextCompilationRequest,
        sections: list[ContextSection],
        omissions: list[ContextOmission],
        compiled_at_ms: int,
    ) -> SpecialistContextBundle:
        sections = sorted(sections, key=context_section_sort_key)
        omissions = sorted(omissions, key=context_omission_sort_key)
        for _ in range(1_024):
            candidate = _build_bundle(
                authority=authority,
                request=request,
                policy=self._policy,
                sections=tuple(sections),
                omissions=tuple(omissions),
                compiled_at_ms=compiled_at_ms,
                validate_limits=False,
            )
            over_bytes = candidate.total_bytes > self._policy.limits.max_total_bytes
            over_tokens = (
                candidate.estimated_tokens
                > self._policy.limits.max_estimated_tokens
            )
            if not over_bytes and not over_tokens:
                return SpecialistContextBundle.model_validate(
                    candidate.model_dump(mode="json")
                )
            optional_indices = [
                index for index, section in enumerate(sections) if not section.required
            ]
            if not optional_indices:
                raise ContextCompilerLimitError(
                    "required context authority cannot fit compiler limits"
                )
            index = optional_indices[-1]
            current = sections[index]
            reason = (
                ContextOmissionReason.BYTE_LIMIT
                if over_bytes
                else ContextOmissionReason.TOKEN_LIMIT
            )
            report = ContextOmission(
                material_id=current.material_id,
                request_id=current.request_id,
                source_kind=current.source_kind,
                source_id=current.source_id,
                source_sha256=current.source_sha256,
                reason=reason,
            )
            if len(current.content) > 1:
                reduced_length = max(1, len(current.content) // 2)
                sections[index] = _truncate_section(
                    current,
                    current.content[:reduced_length],
                )
                _append_report_once(omissions, report)
            else:
                sections.pop(index)
                _append_report_once(omissions, report)
            omissions = sorted(omissions, key=context_omission_sort_key)
            if len(omissions) > self._policy.limits.max_omissions:
                raise ContextCompilerLimitError(
                    "context compaction omission report exceeds limit"
                )
        raise ContextCompilerLimitError("context compaction did not converge")

    def _require_still_active(self, request_id: UUID, *, now_ms: int) -> None:
        entry = self._task_store.get(request_id)
        if entry is None:
            raise ContextCompilerCancelledError("context task disappeared")
        record = entry.record
        if (
            record.phase == AgentTaskPhase.CANCELLED
            or record.budget.cancelled
            or self._invocations.get_cancellation_fence(request_id) is not None
        ):
            raise ContextCompilerCancelledError(
                "cancellation won the race with context compilation"
            )
        if record.phase != AgentTaskPhase.ROUTED:
            raise ContextCompilerCancelledError(
                "task authority changed before context handoff"
            )
        if record.task.deadline_at_ms is not None and now_ms >= record.task.deadline_at_ms:
            raise ContextCompilerCancelledError(
                "task deadline expired before context handoff"
            )

    def _emit_result(self, result: ContextCompilationResult) -> None:
        bundle = result.bundle
        self._trace_sink.emit(
            trace_event(
                request_id=bundle.request_id,
                invocation_id=bundle.specialist_invocation_id,
                kind=(
                    TraceEventKind.CONTEXT_REPLAYED
                    if result.replayed
                    else TraceEventKind.CONTEXT_COMPILED
                ),
                agent_id=bundle.agent_id,
                agent_version=bundle.agent_version,
                cache=(
                    CacheDisposition.HIT
                    if result.replayed
                    else CacheDisposition.MISS
                ),
                outcome="completed",
                reason="bounded specialist context authority committed",
                metadata={
                    "compiler_version": bundle.compiler_version,
                    "context_bundle_id": str(bundle.context_bundle_id),
                    "context_sha256": bundle.canonical_sha256,
                    "source_manifest_sha256": bundle.source_manifest_sha256,
                    "section_count": bundle.section_count,
                    "evidence_count": bundle.evidence_count,
                    "tool_count": bundle.tool_count,
                    "omission_count": bundle.omission_count,
                    "total_bytes": bundle.total_bytes,
                    "estimated_unit_count": bundle.estimated_tokens,
                    "privacy": bundle.privacy.value,
                    "retention": bundle.retention.value,
                    "tainted": bundle.tainted,
                },
                wall_clock_millis=self._wall_clock_millis,
            )
        )

    def _emit_failure(
        self,
        *,
        request: ContextCompilationRequest,
        failure: Exception,
    ) -> None:
        self._trace_sink.emit(
            trace_event(
                request_id=request.request_id,
                invocation_id=request.specialist_invocation_id,
                kind=TraceEventKind.CONTEXT_FAILED,
                agent_id=request.agent_id,
                agent_version=request.agent_version,
                cache=CacheDisposition.BYPASSED_POLICY,
                outcome="failed",
                reason=failure.__class__.__name__,
                metadata={
                    "compiler_version": self._policy.compiler_version,
                    "failure_type": failure.__class__.__name__,
                },
                wall_clock_millis=self._wall_clock_millis,
            )
        )

    def _now_ms(self) -> int:
        return max(0, int(self._wall_clock_millis()))


def _build_bundle(
    *,
    authority: _Authority,
    request: ContextCompilationRequest,
    policy: ContextCompilerPolicy,
    sections: tuple[ContextSection, ...],
    omissions: tuple[ContextOmission, ...],
    compiled_at_ms: int,
    validate_limits: bool,
) -> SpecialistContextBundle:
    if not sections:
        raise ContextCompilerLimitError("context bundle requires at least one section")
    task_kind = authority.record.task.explicit_task_kind
    if task_kind is None:
        if len(authority.definition.task_kinds) != 1:
            raise ContextCompilerPolicyError("implicit task kind is ambiguous")
        task_kind = next(iter(authority.definition.task_kinds))
    source_manifest = context_source_manifest_sha256(sections, omissions)
    canonical_tool_schemas = tuple(
        sorted(
            request.tool_schemas,
            key=lambda item: (item.tool_id, item.connector_id or ""),
        )
    )
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "compiler_id": policy.compiler_id,
        "compiler_version": policy.compiler_version,
        "request_id": str(request.request_id),
        "specialist_invocation_id": str(request.specialist_invocation_id),
        "agent_id": request.agent_id,
        "agent_version": request.agent_version,
        "task_fingerprint": authority.task_fingerprint,
        "routing_fingerprint": authority.routing_fingerprint,
        "policy_fingerprint": authority.policy_fingerprint,
        "task_kind": task_kind.value,
        "execution_mode": authority.record.task.execution_mode.value,
        "freshness": authority.record.task.freshness.value,
        "deadline_at_ms": authority.record.task.deadline_at_ms,
        "capabilities": request.capabilities.model_dump(mode="json"),
        "budget": authority.budget.model_dump(mode="json"),
        "limits": policy.limits.model_dump(mode="json"),
        "output_schema": request.output_schema.model_dump(mode="json"),
        "tool_schemas": [
            item.model_dump(mode="json") for item in canonical_tool_schemas
        ],
        "sections": [item.model_dump(mode="json") for item in sections],
        "omissions": [item.model_dump(mode="json") for item in omissions],
        "source_manifest_sha256": source_manifest,
        "privacy": strictest_privacy(
            (section.privacy for section in sections),
            default=PrivacyClassification.INTERNAL,
        ).value,
        "retention": strictest_retention(
            (section.retention for section in sections),
            default=RetentionDisposition.SESSION,
        ).value,
        "tainted": any(section.tainted for section in sections),
    }
    canonical_hash = context_bundle_canonical_sha256(payload)
    identity_payload = context_bundle_canonical_payload(payload)
    total_bytes = canonical_size_bytes(identity_payload)
    estimated_tokens = estimate_context_tokens(canonical_json(identity_payload))
    bundle_fields = dict(
        context_bundle_id=context_bundle_id_for(
            request_id=request.request_id,
            canonical_sha256=canonical_hash,
        ),
        canonical_sha256=canonical_hash,
        request_id=request.request_id,
        specialist_invocation_id=request.specialist_invocation_id,
        agent_id=request.agent_id,
        agent_version=request.agent_version,
        task_fingerprint=authority.task_fingerprint,
        routing_fingerprint=authority.routing_fingerprint,
        policy_fingerprint=authority.policy_fingerprint,
        task_kind=task_kind,
        execution_mode=authority.record.task.execution_mode,
        freshness=authority.record.task.freshness,
        deadline_at_ms=authority.record.task.deadline_at_ms,
        capabilities=request.capabilities,
        budget=authority.budget,
        limits=policy.limits,
        output_schema=request.output_schema,
        tool_schemas=canonical_tool_schemas,
        sections=sections,
        omissions=omissions,
        source_manifest_sha256=source_manifest,
        privacy=strictest_privacy(
            (section.privacy for section in sections),
            default=PrivacyClassification.INTERNAL,
        ),
        retention=strictest_retention(
            (section.retention for section in sections),
            default=RetentionDisposition.SESSION,
        ),
        tainted=any(section.tainted for section in sections),
        section_count=len(sections),
        evidence_count=sum(
            section.source_kind == ContextSourceKind.EVIDENCE for section in sections
        ),
        tool_count=len(canonical_tool_schemas),
        omission_count=len(omissions),
        total_bytes=total_bytes,
        estimated_tokens=estimated_tokens,
        compiled_at_ms=compiled_at_ms,
        replay=ContextReplayDisposition.FRESH,
    )
    if validate_limits:
        return SpecialistContextBundle.model_validate(bundle_fields)
    return SpecialistContextBundle.model_construct(
        **cast(Any, bundle_fields)
    )


def _material_sort_key(
    material: ContextMaterial,
) -> tuple[int, int, int, str, str]:
    kind_rank = {
        ContextSourceKind.USER_TASK: 0,
        ContextSourceKind.PROJECT_GOAL: 1,
        ContextSourceKind.DECISION: 2,
        ContextSourceKind.RESULT_REFERENCE: 3,
        ContextSourceKind.EVIDENCE: 4,
    }[material.source_kind]
    return (
        kind_rank,
        0 if material.required else 1,
        -material.priority,
        material.source_id,
        str(material.material_id),
    )


def _omission(
    material: ContextMaterial,
    reason: ContextOmissionReason,
) -> ContextOmission:
    return ContextOmission(
        material_id=material.material_id,
        request_id=material.request_id,
        source_kind=material.source_kind,
        source_id=material.source_id,
        source_sha256=material.source_sha256,
        reason=reason,
    )


def _append_report_once(
    reports: list[ContextOmission],
    report: ContextOmission,
) -> None:
    identity = (
        report.material_id,
        report.request_id,
        report.source_kind,
        report.source_id,
        report.source_sha256,
        report.reason,
    )
    if any(
        (
            current.material_id,
            current.request_id,
            current.source_kind,
            current.source_id,
            current.source_sha256,
            current.reason,
        )
        == identity
        for current in reports
    ):
        return
    reports.append(report)


def _truncate_section(section: ContextSection, content: str) -> ContextSection:
    if section.required:
        raise ContextCompilerLimitError("required context section cannot be truncated")
    if not content or not section.content.startswith(content):
        raise ContextCompilerLimitError(
            "context compaction must preserve a non-empty deterministic prefix"
        )
    return ContextSection(
        material_id=section.material_id,
        request_id=section.request_id,
        source_kind=section.source_kind,
        trust=section.trust,
        source_id=section.source_id,
        source_sha256=section.source_sha256,
        content_sha256=context_text_sha256(content),
        content=content,
        disposition=ContextSectionDisposition.TRUNCATED,
        original_characters=section.original_characters,
        included_characters=len(content),
        byte_count=len(content.encode("utf-8")),
        estimated_tokens=estimate_context_tokens(content),
        required=False,
        priority=section.priority,
        observed_at_ms=section.observed_at_ms,
        fresh_until_ms=section.fresh_until_ms,
        cache_disposition=section.cache_disposition,
        content_addressed=section.content_addressed,
        tainted=section.tainted,
        privacy=section.privacy,
        retention=section.retention,
        citation_reference=section.citation_reference,
    )


def _context_budget_projection(
    *,
    record: AgentTaskRecord,
    effective_budget: TaskBudget,
) -> ContextBudgetProjection:
    remaining = context_remaining_usage(
        limits=effective_budget,
        committed=record.budget.committed,
        reserved=record.budget.reserved,
    )
    payload = {
        "schema_version": "1.0",
        "request_id": str(record.request_id),
        "effective_limits": effective_budget.model_dump(mode="json"),
        "committed": record.budget.committed.model_dump(mode="json"),
        "reserved": record.budget.reserved.model_dump(mode="json"),
        "remaining": remaining.model_dump(mode="json"),
        "elapsed_ms": record.budget.elapsed_ms,
        "remaining_elapsed_ms": max(
            0,
            effective_budget.max_elapsed_ms - record.budget.elapsed_ms,
        ),
        "cancelled": record.budget.cancelled,
        "exhausted_dimension": record.budget.exhausted_dimension,
    }
    return ContextBudgetProjection.model_validate(
        {
            **payload,
            "canonical_sha256": canonical_fingerprint(payload),
        }
    )


def _maximum_capabilities(
    *,
    record: AgentTaskRecord,
    definition: SpecialistDefinition,
) -> SpecialistCapabilitySet:
    connectors = definition.connector_allowlist.intersection(
        record.task.allowed_data_sources
    )
    model_tiers = (
        frozenset(definition.model_policy.allowed_tiers)
        if definition.model_policy.maximum_model_calls > 0
        else frozenset()
    )
    proposal_allowed = definition.side_effect_policy in {
        SideEffectPolicy.PROPOSE_ONLY,
        SideEffectPolicy.TYPED_EXECUTOR_ONLY,
    }
    mutation_allowed = (
        definition.side_effect_policy == SideEffectPolicy.TYPED_EXECUTOR_ONLY
        and record.task.execution_mode == ExecutionMode.EXECUTE_TYPED
    )
    return SpecialistCapabilitySet(
        tool_ids=definition.tool_allowlist,
        connector_ids=connectors,
        model_tiers=model_tiers,
        proposal_allowed=proposal_allowed,
        typed_mutation_allowed=mutation_allowed,
    )


def _require_effect_capability(
    *,
    record: AgentTaskRecord,
    definition: SpecialistDefinition,
    request: ContextCompilationRequest,
) -> None:
    if record.task.execution_mode == ExecutionMode.ROUTE_ONLY:
        raise ContextCompilerPolicyError("route-only task cannot compile execution context")
    if record.task.execution_mode == ExecutionMode.EXECUTE_TYPED:
        if definition.side_effect_policy != SideEffectPolicy.TYPED_EXECUTOR_ONLY:
            raise ContextCompilerPolicyError(
                "typed execution context requires typed-executor specialist policy"
            )
        if not request.capabilities.typed_mutation_allowed:
            raise ContextCompilerPolicyError(
                "typed execution context requires explicit mutation capability"
            )
    elif (
        definition.side_effect_policy == SideEffectPolicy.PROPOSE_ONLY
        and not request.capabilities.proposal_allowed
    ):
        raise ContextCompilerPolicyError(
            "proposal context requires explicit proposal capability"
        )


def _policy_fingerprint(
    *,
    definition: SpecialistDefinition,
    capabilities: SpecialistCapabilitySet,
    task_record: AgentTaskRecord,
    compiler_policy: ContextCompilerPolicy,
) -> str:
    model_policy = definition.model_policy
    payload = {
        "agent_id": definition.agent_id,
        "version": definition.version,
        "task_kinds": sorted(item.value for item in definition.task_kinds),
        "locale_prefixes": sorted(definition.locale_prefixes),
        "input_contract": definition.input_contract,
        "output_contract": definition.output_contract,
        "tool_allowlist": sorted(definition.tool_allowlist),
        "connector_allowlist": sorted(definition.connector_allowlist),
        "model_policy": {
            "allowed_tiers": [item.value for item in model_policy.allowed_tiers],
            "minimum_tier": (
                model_policy.minimum_tier.value
                if model_policy.minimum_tier is not None
                else None
            ),
            "maximum_model_calls": model_policy.maximum_model_calls,
            "classifier_allowed": model_policy.classifier_allowed,
            "escalation_agent_ids": list(model_policy.escalation_agent_ids),
        },
        "budget_ceiling": definition.budget_ceiling.model_dump(mode="json"),
        "side_effect_policy": definition.side_effect_policy.value,
        "capabilities": {
            "tool_ids": sorted(capabilities.tool_ids),
            "connector_ids": sorted(capabilities.connector_ids),
            "model_tiers": sorted(item.value for item in capabilities.model_tiers),
            "proposal_allowed": capabilities.proposal_allowed,
            "typed_mutation_allowed": capabilities.typed_mutation_allowed,
        },
        "task_budget_snapshot": task_record.budget.model_dump(mode="json"),
        "compiler_policy": compiler_policy.model_dump(mode="json"),
    }
    return canonical_fingerprint(payload)


def _privacy_rank(value: PrivacyClassification) -> int:
    return {
        PrivacyClassification.PUBLIC: 0,
        PrivacyClassification.INTERNAL: 1,
        PrivacyClassification.PRIVATE: 2,
        PrivacyClassification.SENSITIVE: 3,
        PrivacyClassification.RESTRICTED: 4,
    }[value]


def _retention_rank(value: RetentionDisposition) -> int:
    return {
        RetentionDisposition.TRANSIENT: 0,
        RetentionDisposition.SESSION: 1,
        RetentionDisposition.PROJECT: 2,
        RetentionDisposition.LONG_LIVED: 3,
        RetentionDisposition.LEGAL_HOLD: 4,
    }[value]


__all__ = [
    "ContextCompilationResult",
    "ContextCompilerCancelledError",
    "ContextCompilerDisabledError",
    "ContextCompilerError",
    "ContextCompilerFreshnessError",
    "ContextCompilerLimitError",
    "ContextCompilerPolicyError",
    "ContextCompilerService",
]
