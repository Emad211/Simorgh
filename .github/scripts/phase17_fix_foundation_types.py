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
''',
        '''def context_remaining_usage(
    *,
    limits: TaskBudget,
    committed: UsageVector,
    reserved: UsageVector,
) -> UsageVector:
    committed_values = committed.model_dump()
    reserved_values = reserved.model_dump()

    def remaining(dimension: str) -> int:
        committed_value = int(committed_values[dimension])
        reserved_value = int(reserved_values[dimension])
        return max(
            0,
            limits.limit_for(dimension) - committed_value - reserved_value,
        )

    return UsageVector(
''',
        label="strict remaining budget typing",
    )


def patch_projections() -> None:
    path = "services/core/src/simorgh_core/agents/context_projections.py"
    replace_once(
        path,
        '''        projections.append(
            ContextToolSchemaProjection(
                **payload,
                canonical_sha256=canonical_fingerprint(payload),
            )
        )
''',
        '''        projections.append(
            ContextToolSchemaProjection(
                schema_version=CONTEXT_CONTRACT_VERSION,
                tool_id=definition.tool_id,
                connector_id=manifest.connector_id,
                effect=InvocationEffect.READ_ONLY,
                input_contract=definition.input_contract,
                output_contract=definition.output_contract,
                description=_GITHUB_DESCRIPTIONS[operation],
                input_schema=_GITHUB_INPUT_MODELS[operation].model_json_schema(
                    mode="validation"
                ),
                output_schema=_GITHUB_OUTPUT_MODELS[operation].model_json_schema(
                    mode="validation"
                ),
                canonical_sha256=canonical_fingerprint(payload),
            )
        )
''',
        label="explicit tool schema projection construction",
    )
    replace_once(
        path,
        '''    return ContextOutputSchemaProjection(
        **payload,
        canonical_sha256=canonical_fingerprint(payload),
    )
''',
        '''    return ContextOutputSchemaProjection(
        schema_version=CONTEXT_CONTRACT_VERSION,
        output_contract=handler.output_contract,
        result_schema_id=handler.schema_id,
        result_schema_version=handler.schema_version,
        family=handler.family,
        json_schema=SpecialistPlanPayload.model_json_schema(mode="validation"),
        canonical_sha256=canonical_fingerprint(payload),
    )
''',
        label="explicit output schema projection construction",
    )


def patch_compiler() -> None:
    path = "services/core/src/simorgh_core/agents/context_compiler.py"
    replace_once(
        path,
        "from dataclasses import dataclass\nfrom uuid import UUID\n",
        "from dataclasses import dataclass\nfrom typing import Any, cast\nfrom uuid import UUID\n",
        label="typed provisional bundle imports",
    )
    replace_once(
        path,
        '''    if validate_limits:
        return SpecialistContextBundle(**bundle_fields)
    return SpecialistContextBundle.model_construct(**bundle_fields)
''',
        '''    if validate_limits:
        return SpecialistContextBundle.model_validate(bundle_fields)
    return SpecialistContextBundle.model_construct(
        **cast(Any, bundle_fields)
    )
''',
        label="typed provisional bundle construction",
    )
    replace_once(
        path,
        '''    return ContextBudgetProjection(
        **payload,
        canonical_sha256=canonical_fingerprint(payload),
    )
''',
        '''    return ContextBudgetProjection.model_validate(
        {
            **payload,
            "canonical_sha256": canonical_fingerprint(payload),
        }
    )
''',
        label="typed context budget projection construction",
    )


def main() -> None:
    patch_contracts()
    patch_projections()
    patch_compiler()


if __name__ == "__main__":
    main()
