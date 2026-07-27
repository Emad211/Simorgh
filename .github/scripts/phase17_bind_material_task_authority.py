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
        '''    material_id: UUID
    source_kind: ContextSourceKind
''',
        '''    material_id: UUID
    request_id: UUID
    source_kind: ContextSourceKind
''',
        label="material task ownership",
    )
    replace_once(
        path,
        '''class ContextSection(BaseModel):
    """One immutable admitted context data section; authority remains top-level."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CONTEXT_CONTRACT_VERSION
    material_id: UUID
    source_kind: ContextSourceKind
''',
        '''class ContextSection(BaseModel):
    """One immutable admitted context data section; authority remains top-level."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CONTEXT_CONTRACT_VERSION
    material_id: UUID
    request_id: UUID
    source_kind: ContextSourceKind
''',
        label="section task ownership",
    )
    replace_once(
        path,
        '''    schema_version: Literal["1.0"] = CONTEXT_CONTRACT_VERSION
    material_id: UUID
    source_kind: ContextSourceKind
    source_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
''',
        '''    schema_version: Literal["1.0"] = CONTEXT_CONTRACT_VERSION
    material_id: UUID
    request_id: UUID
    source_kind: ContextSourceKind
    source_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
''',
        label="omission task ownership",
    )
    replace_once(
        path,
        '''    return ContextSection(
        material_id=material.material_id,
        source_kind=material.source_kind,
''',
        '''    return ContextSection(
        material_id=material.material_id,
        request_id=material.request_id,
        source_kind=material.source_kind,
''',
        label="section material ownership projection",
    )
    replace_once(
        path,
        '''            {
                "material_id": str(section.material_id),
                "source_kind": section.source_kind.value,
''',
        '''            {
                "material_id": str(section.material_id),
                "request_id": str(section.request_id),
                "source_kind": section.source_kind.value,
''',
        label="source manifest task ownership",
    )


def patch_sources() -> None:
    path = "services/core/src/simorgh_core/agents/context_sources.py"
    replace_once(
        path,
        '''    return ContextMaterial(
        material_id=context_material_id_for(
''',
        '''    return ContextMaterial(
        material_id=context_material_id_for(
''',
        label="GitHub material constructor anchor",
    )
    replace_once(
        path,
        '''            source_sha256=validated.projection_sha256,
        ),
        source_kind=ContextSourceKind.EVIDENCE,
''',
        '''            source_sha256=validated.projection_sha256,
        ),
        request_id=request_id,
        source_kind=ContextSourceKind.EVIDENCE,
''',
        label="GitHub material task ownership",
    )


def patch_compiler() -> None:
    path = "services/core/src/simorgh_core/agents/context_compiler.py"
    replace_once(
        path,
        '''        user_material = ContextMaterial(
            material_id=context_material_id_for(
''',
        '''        user_material = ContextMaterial(
            material_id=context_material_id_for(
''',
        label="user material constructor anchor",
    )
    replace_once(
        path,
        '''                source_sha256=user_source_sha,
            ),
            source_kind=ContextSourceKind.USER_TASK,
''',
        '''                source_sha256=user_source_sha,
            ),
            request_id=record.request_id,
            source_kind=ContextSourceKind.USER_TASK,
''',
        label="user material task ownership",
    )
    replace_once(
        path,
        '''        approved = tuple(
            self._materials.require(material) for material in request.materials
        )
        materials = (user_material, *approved)
''',
        '''        approved = tuple(
            self._materials.require(material) for material in request.materials
        )
        if any(material.request_id != record.request_id for material in approved):
            raise ContextCompilerPolicyError(
                "context material does not belong to task"
            )
        materials = (user_material, *approved)
''',
        label="approved material task ownership check",
    )
    replace_once(
        path,
        '''                    ContextOmission(
                        material_id=current.material_id,
                        source_kind=current.source_kind,
''',
        '''                    ContextOmission(
                        material_id=current.material_id,
                        request_id=current.request_id,
                        source_kind=current.source_kind,
''',
        label="compaction omission task ownership",
    )
    replace_once(
        path,
        '''    return ContextOmission(
        material_id=material.material_id,
        source_kind=material.source_kind,
''',
        '''    return ContextOmission(
        material_id=material.material_id,
        request_id=material.request_id,
        source_kind=material.source_kind,
''',
        label="filtered omission task ownership",
    )
    replace_once(
        path,
        '''    return ContextSection(
        material_id=section.material_id,
        source_kind=section.source_kind,
''',
        '''    return ContextSection(
        material_id=section.material_id,
        request_id=section.request_id,
        source_kind=section.source_kind,
''',
        label="truncated section task ownership",
    )


def patch_tests() -> None:
    path = "services/core/tests/test_context_compiler.py"
    replace_once(
        path,
        '''        ),
        source_kind=source_kind,
        trust=trust,
''',
        '''        ),
        request_id=request_id,
        source_kind=source_kind,
        trust=trust,
''',
        label="test material task ownership",
    )
    replace_once(
        path,
        '''    service, task, *_ = _runtime(approved_materials=(malicious,))
''',
        '''    service, task, *_ = _runtime(
        task=task,
        approved_materials=(malicious,),
    )
''',
        label="injection runtime task identity",
    )
    replace_once(
        path,
        '''def test_unapproved_material_is_rejected_before_compilation() -> None:
''',
        '''def test_approved_material_from_another_task_is_rejected() -> None:
    task = _task()
    foreign_task = _task()
    foreign = _material(
        request_id=foreign_task.request_id,
        source_kind=ContextSourceKind.EVIDENCE,
        source_id="github.foreign",
        content="foreign evidence",
    )
    service, *_ = _runtime(
        task=task,
        approved_materials=(foreign,),
    )

    with pytest.raises(ContextCompilerPolicyError, match="does not belong"):
        service.compile(
            _request(task=task, invocation_id=uuid4(), materials=(foreign,))
        )


def test_unapproved_material_is_rejected_before_compilation() -> None:
''',
        label="cross-task material rejection test",
    )


def patch_contract_tests() -> None:
    path = "services/core/tests/test_context_contracts.py"
    replace_once(
        path,
        '''        ),
        source_kind=ContextSourceKind.EVIDENCE,
        trust=trust,
''',
        '''        ),
        request_id=request_id,
        source_kind=ContextSourceKind.EVIDENCE,
        trust=trust,
''',
        label="contract test material task ownership",
    )


def main() -> None:
    patch_contracts()
    patch_sources()
    patch_compiler()
    patch_tests()
    patch_contract_tests()


if __name__ == "__main__":
    main()
