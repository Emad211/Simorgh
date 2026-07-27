from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, *, label: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: count={count}, expected=1")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


path = "services/core/tests/test_context_compiler.py"
replace_once(
    path,
    '''    ContextCompilerFreshnessError,
    ContextCompilerPolicyError,
''',
    '''    ContextCompilerFreshnessError,
    ContextCompilerLimitError,
    ContextCompilerPolicyError,
''',
    label="context limit test import",
)
replace_once(
    path,
    '''def test_context_trace_contains_only_bounded_authority_metadata() -> None:
''',
    '''def test_required_material_overflow_fails_closed_without_truncation() -> None:
    task = _task()
    required = _material(
        request_id=task.request_id,
        source_kind=ContextSourceKind.PROJECT_GOAL,
        source_id="project.required-overflow",
        content="r" * 500,
        required=True,
        fresh_until_ms=None,
    )
    policy = ContextCompilerPolicy(
        limits=ContextCompilerLimits(max_text_characters=100)
    )
    service, *_ = _runtime(
        task=task,
        policy=policy,
        approved_materials=(required,),
    )

    with pytest.raises(ContextCompilerLimitError, match="required"):
        service.compile(
            _request(
                task=task,
                invocation_id=uuid4(),
                materials=(required,),
            )
        )


def test_compiler_policy_change_produces_a_new_context_identity() -> None:
    task = _task()
    invocation_id = uuid4()
    request = _request(task=task, invocation_id=invocation_id)
    first_service, *_ = _runtime(
        task=task,
        policy=ContextCompilerPolicy(
            limits=ContextCompilerLimits(max_sections=48)
        ),
    )
    second_service, *_ = _runtime(
        task=task,
        policy=ContextCompilerPolicy(
            limits=ContextCompilerLimits(max_sections=47)
        ),
    )

    first = first_service.compile(request)
    second = second_service.compile(request)

    assert first.bundle.policy_fingerprint != second.bundle.policy_fingerprint
    assert first.bundle.canonical_sha256 != second.bundle.canonical_sha256
    assert first.bundle.context_bundle_id != second.bundle.context_bundle_id


def test_context_trace_contains_only_bounded_authority_metadata() -> None:
''',
    label="context limit and identity acceptance tests",
)
