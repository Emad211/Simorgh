from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, *, label: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: count={count}, expected=1")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_contracts() -> None:
    path = "services/core/src/simorgh_core/agents/context_contracts.py"
    replace_once(
        path,
        "    FreshnessClass,\n    TaskBudget,\n    TaskKind,\n",
        "    FreshnessClass,\n    TaskBudget,\n    TaskKind,\n    UsageVector,\n",
        label="context usage import",
    )
    replace_once(
        path,
        "    output_schema: ContextOutputSchemaProjection\n    compiled_at_ms: int = Field(ge=0)\n\n",
        "    output_schema: ContextOutputSchemaProjection\n\n",
        label="remove caller-authored compile time",
    )
    replace_once(
        path,
        '''class ContextCompilerPolicy(BaseModel):
''',
        '''class ContextBudgetProjection(BaseModel):
    """Machine-verifiable remaining specialist budget at compilation time."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CONTEXT_CONTRACT_VERSION
    request_id: UUID
    effective_limits: TaskBudget
    committed: UsageVector
    reserved: UsageVector
    remaining: UsageVector
    elapsed_ms: int = Field(ge=0)
    remaining_elapsed_ms: int = Field(ge=0)
    cancelled: bool
    exhausted_dimension: str | None = None
    canonical_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )

    @model_validator(mode="after")
    def validate_budget(self) -> Self:
        expected_remaining = context_remaining_usage(
            limits=self.effective_limits,
            committed=self.committed,
            reserved=self.reserved,
        )
        if self.remaining != expected_remaining:
            raise ValueError("context remaining budget does not match usage and limits")
        expected_elapsed = max(0, self.effective_limits.max_elapsed_ms - self.elapsed_ms)
        if self.remaining_elapsed_ms != expected_elapsed:
            raise ValueError("context remaining elapsed budget is invalid")
        if context_budget_projection_sha256(self) != self.canonical_sha256:
            raise ValueError("context budget projection hash does not match content")
        return self


class ContextCompilerPolicy(BaseModel):
''',
        label="context budget projection contract",
    )
    replace_once(
        path,
        "    effective_budget: TaskBudget\n    limits: ContextCompilerLimits\n",
        "    budget: ContextBudgetProjection\n    limits: ContextCompilerLimits\n",
        label="bundle budget projection field",
    )
    replace_once(
        path,
        '''        if self.section_count != len(self.sections):
            raise ValueError("context bundle section count is invalid")
''',
        '''        if self.budget.request_id != self.request_id:
            raise ValueError("context bundle budget does not belong to request")
        if self.budget.cancelled:
            raise ValueError("cancelled budget cannot authorize a context bundle")
        if self.section_count != len(self.sections):
            raise ValueError("context bundle section count is invalid")
''',
        label="bundle budget authority validation",
    )
    replace_once(
        path,
        "        if context_source_manifest_sha256(self.sections, self.omissions) != self.source_manifest_sha256:\n",
        "        if (\n            context_source_manifest_sha256(self.sections, self.omissions)\n            != self.source_manifest_sha256\n        ):\n",
        label="context manifest line length",
    )
    replace_once(
        path,
        '''def context_text_sha256(value: str) -> str:
''',
        '''def context_remaining_usage(
    *,
    limits: TaskBudget,
    committed: UsageVector,
    reserved: UsageVector,
) -> UsageVector:
    def remaining(dimension: str) -> int:
        return max(
            0,
            limits.limit_for(dimension)
            - getattr(committed, dimension)
            - getattr(reserved, dimension),
        )

    return UsageVector(
        model_calls=remaining("model_calls"),
        tool_calls=remaining("tool_calls"),
        input_tokens=remaining("input_tokens"),
        output_tokens=remaining("output_tokens"),
        estimated_cost_microusd=remaining("estimated_cost_microusd"),
        retries=remaining("retries"),
        parallel_branches=remaining("parallel_branches"),
    )


def context_budget_projection_sha256(value: ContextBudgetProjection) -> str:
    return canonical_fingerprint(
        value.model_dump(mode="json", exclude={"canonical_sha256"})
    )


def context_text_sha256(value: str) -> str:
''',
        label="context budget helpers",
    )
    replace_once(
        path,
        '''    for field in (
        "context_bundle_id",
''',
        '''    capabilities = payload.get("capabilities")
    if isinstance(capabilities, dict):
        for key in ("tool_ids", "connector_ids", "model_tiers"):
            values = capabilities.get(key)
            if isinstance(values, list):
                capabilities[key] = sorted(values)
    for field in (
        "context_bundle_id",
''',
        label="canonical capability ordering",
    )
    replace_once(
        path,
        '''    "ContextCompilationRequest",
    "ContextCompilerLimits",
''',
        '''    "ContextBudgetProjection",
    "ContextCompilationRequest",
    "ContextCompilerLimits",
''',
        label="context budget export",
    )
    replace_once(
        path,
        '''    "context_bundle_id_for",
    "context_material_id_for",
''',
        '''    "context_bundle_id_for",
    "context_budget_projection_sha256",
    "context_material_id_for",
''',
        label="context budget hash export",
    )
    replace_once(
        path,
        '''    "context_output_schema_sha256",
    "context_section_from_material",
''',
        '''    "context_output_schema_sha256",
    "context_remaining_usage",
    "context_section_from_material",
''',
        label="remaining budget export",
    )


def patch_projections() -> None:
    path = "services/core/src/simorgh_core/agents/context_projections.py"
    replace_once(
        path,
        '''    GitHubReadOperation.FETCH_FILE: "Fetch one bounded UTF-8 GitHub file projection at an explicit ref.",
''',
        '''    GitHubReadOperation.FETCH_FILE: (
        "Fetch one bounded UTF-8 GitHub file projection at an explicit ref."
    ),
''',
        label="projection description line length",
    )


def patch_compiler() -> None:
    path = "services/core/src/simorgh_core/agents/context_compiler.py"
    replace_once(
        path,
        "from typing import NoReturn\n",
        "",
        label="remove unused NoReturn import",
    )
    replace_once(
        path,
        "    ContextCompilationRequest,\n    ContextCompilerPolicy,\n",
        "    ContextBudgetProjection,\n    ContextCompilationRequest,\n    ContextCompilerPolicy,\n",
        label="compiler budget projection import",
    )
    replace_once(
        path,
        "    ContextOutputSchemaProjection,\n",
        "",
        label="remove unused output schema import",
    )
    replace_once(
        path,
        "    ContextReplayDisposition,\n    ContextSection,\n",
        "    ContextReplayDisposition,\n    ContextSection,\n    ContextSectionDisposition,\n",
        label="compiler section disposition import",
    )
    replace_once(
        path,
        "    context_bundle_id_for,\n    context_material_id_for,\n",
        "    context_budget_projection_sha256,\n    context_bundle_id_for,\n    context_material_id_for,\n",
        label="compiler budget hash import",
    )
    replace_once(
        path,
        "    context_output_schema_sha256,\n" if False else "",
        "",
        label="never",
    ) if False else None
    replace_once(
        path,
        "    context_omission_sort_key,\n    context_section_from_material,\n",
        "    context_omission_sort_key,\n    context_remaining_usage,\n    context_section_from_material,\n",
        label="compiler remaining usage import",
    )
    replace_once(
        path,
        '''    policy_fingerprint: str
''',
        '''    policy_fingerprint: str
    budget: ContextBudgetProjection
''',
        label="authority budget projection",
    )
    replace_once(
        path,
        '''        materials = self._prepare_materials(
            record=authority.record,
            request=request,
        )
''',
        '''        materials = self._prepare_materials(
            record=authority.record,
            task_fingerprint=authority.task_fingerprint,
            request=request,
        )
''',
        label="authoritative user source fingerprint",
    )
    replace_once(
        path,
        '''        return _Authority(
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
        )
''',
        '''        return _Authority(
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
''',
        label="compile remaining budget projection",
    )
    replace_once(
        path,
        '''            if projection.effect == InvocationEffect.MUTATION:
                if not request.capabilities.typed_mutation_allowed:
                    raise ContextCompilerPolicyError(
                        "mutation tool schema requires typed mutation capability"
                    )
''',
        '''            if (
                projection.effect == InvocationEffect.MUTATION
                and not request.capabilities.typed_mutation_allowed
            ):
                raise ContextCompilerPolicyError(
                    "mutation tool schema requires typed mutation capability"
                )
''',
        label="combine mutation schema policy check",
    )
    replace_once(
        path,
        '''        *,
        record: AgentTaskRecord,
        request: ContextCompilationRequest,
''',
        '''        *,
        record: AgentTaskRecord,
        task_fingerprint: str,
        request: ContextCompilationRequest,
''',
        label="prepare material signature",
    )
    replace_once(
        path,
        '''                "request_id": str(record.request_id),
                "task_fingerprint": canonical_fingerprint(record.task),
''',
        '''                "request_id": str(record.request_id),
                "task_fingerprint": task_fingerprint,
''',
        label="stable task source hash",
    )
    replace_once(
        path,
        '''                material = _material_from_section(current)
                sections[index] = context_section_from_material(
                    material,
                    content=current.content[:reduced_length],
                )
''',
        '''                sections[index] = _truncate_section(
                    current,
                    current.content[:reduced_length],
                )
''',
        label="preserve original truncation metadata",
    )
    replace_once(
        path,
        '''        "effective_budget": authority.effective_budget.model_dump(mode="json"),
        "limits": policy.limits.model_dump(mode="json"),
''',
        '''        "budget": authority.budget.model_dump(mode="json"),
        "limits": policy.limits.model_dump(mode="json"),
''',
        label="canonical budget projection payload",
    )
    replace_once(
        path,
        '''        effective_budget=authority.effective_budget,
        limits=policy.limits,
''',
        '''        budget=authority.budget,
        limits=policy.limits,
''',
        label="bundle budget projection",
    )
    replace_once(
        path,
        '''    bundle = SpecialistContextBundle(
''',
        '''    bundle_fields = dict(
''',
        label="provisional bundle fields",
    )
    replace_once(
        path,
        '''        replay=ContextReplayDisposition.FRESH,
    )
    if validate_limits:
        return SpecialistContextBundle.model_validate(bundle.model_dump(mode="json"))
    return bundle
''',
        '''        replay=ContextReplayDisposition.FRESH,
    )
    if validate_limits:
        return SpecialistContextBundle(**bundle_fields)
    return SpecialistContextBundle.model_construct(**bundle_fields)
''',
        label="defer limit validation during deterministic compaction",
    )
    replace_once(
        path,
        '''def _material_from_section(section: ContextSection) -> ContextMaterial:
    return ContextMaterial(
        material_id=section.material_id,
        source_kind=section.source_kind,
        trust=section.trust,
        source_id=section.source_id,
        source_sha256=section.source_sha256,
        content_sha256=section.content_sha256,
        content=section.content,
        required=section.required,
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


''',
        '''def _truncate_section(section: ContextSection, content: str) -> ContextSection:
    if section.required:
        raise ContextCompilerLimitError("required context section cannot be truncated")
    if not content or not section.content.startswith(content):
        raise ContextCompilerLimitError(
            "context compaction must preserve a non-empty deterministic prefix"
        )
    return ContextSection(
        material_id=section.material_id,
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


''',
        label="stable section truncation helper",
    )
    replace_once(
        path,
        '''def _maximum_capabilities(
''',
        '''def _context_budget_projection(
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
    return ContextBudgetProjection(
        **payload,
        canonical_sha256=canonical_fingerprint(payload),
    )


def _maximum_capabilities(
''',
        label="budget projection builder",
    )
    replace_once(
        path,
        '''
def _raise(message: str) -> NoReturn:
    raise ContextCompilerError(message)


''',
        "\n",
        label="remove unused compiler helper",
    )


def main() -> None:
    patch_contracts()
    patch_projections()
    patch_compiler()


if __name__ == "__main__":
    main()
