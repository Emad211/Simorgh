from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, *, label: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: count={count}, expected=1")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_compiler() -> None:
    path = "services/core/src/simorgh_core/agents/context_compiler.py"
    replace_once(
        path,
        '''from simorgh_core.agents.context_store import ContextClaimKind, ContextStore
''',
        '''from simorgh_core.agents.context_sources import ContextMaterialRegistry
from simorgh_core.agents.context_store import ContextClaimKind, ContextStore
''',
        label="context material registry import",
    )
    replace_once(
        path,
        '''        context_store: ContextStore,
        reviewed_tool_schemas: Mapping[str, ContextToolSchemaProjection],
''',
        '''        context_store: ContextStore,
        material_registry: ContextMaterialRegistry | None = None,
        reviewed_tool_schemas: Mapping[str, ContextToolSchemaProjection],
''',
        label="context material registry constructor",
    )
    replace_once(
        path,
        '''        self._contexts = context_store
        self._tool_schemas = dict(reviewed_tool_schemas)
''',
        '''        self._contexts = context_store
        self._materials = material_registry or ContextMaterialRegistry()
        self._tool_schemas = dict(reviewed_tool_schemas)
''',
        label="context material authority assignment",
    )
    replace_once(
        path,
        '''        materials = (user_material, *request.materials)
''',
        '''        approved = tuple(
            self._materials.require(material) for material in request.materials
        )
        materials = (user_material, *approved)
''',
        label="exact context material authority check",
    )


def patch_tests() -> None:
    path = "services/core/tests/test_context_compiler.py"
    replace_once(
        path,
        '''from simorgh_core.agents.context_store import (
''',
        '''from simorgh_core.agents.context_sources import (
    ContextMaterialRegistry,
    UnknownContextMaterialError,
)
from simorgh_core.agents.context_store import (
''',
        label="context source test imports",
    )
    replace_once(
        path,
        '''    invocation_store: InMemoryInvocationStore | None = None,
) -> tuple[
''',
        '''    invocation_store: InMemoryInvocationStore | None = None,
    approved_materials: tuple[ContextMaterial, ...] = (),
) -> tuple[
''',
        label="runtime approved material fixtures",
    )
    replace_once(
        path,
        '''        context_store=contexts,
        reviewed_tool_schemas={item.tool_id: item for item in tool_schemas},
''',
        '''        context_store=contexts,
        material_registry=ContextMaterialRegistry(approved_materials),
        reviewed_tool_schemas={item.tool_id: item for item in tool_schemas},
''',
        label="runtime material registry binding",
    )
    replace_once(
        path,
        '''    first_service, *_ = _runtime(task=task)
    second_service, *_ = _runtime(task=task)
''',
        '''    approved = (project, evidence)
    first_service, *_ = _runtime(task=task, approved_materials=approved)
    second_service, *_ = _runtime(task=task, approved_materials=approved)
''',
        label="order test approved materials",
    )
    replace_once(
        path,
        '''    result = service.compile(
        _request(task=task, invocation_id=uuid4(), materials=(malicious,))
    )
''',
        '''    service, task, *_ = _runtime(approved_materials=(malicious,))
    result = service.compile(
        _request(task=task, invocation_id=uuid4(), materials=(malicious,))
    )
''',
        label="injection test approved material",
    )
    replace_once(
        path,
        '''def test_prompt_injection_stays_untrusted_and_cannot_widen_tools() -> None:
    service, task, *_ = _runtime()
    malicious = _material(
''',
        '''def test_prompt_injection_stays_untrusted_and_cannot_widen_tools() -> None:
    task = _task()
    malicious = _material(
''',
        label="injection test task authority",
    )
    replace_once(
        path,
        '''    service, *_ = _runtime(task=task)
    result = service.compile(
        _request(task=task, invocation_id=uuid4(), materials=(stale,))
    )
''',
        '''    service, *_ = _runtime(task=task, approved_materials=(stale,))
    result = service.compile(
        _request(task=task, invocation_id=uuid4(), materials=(stale,))
    )
''',
        label="stale optional authority",
    )
    replace_once(
        path,
        '''    required = stale.model_copy(update={"required": True})
    with pytest.raises(ContextCompilerFreshnessError, match="fresh"):
        service.compile(
            _request(task=task, invocation_id=uuid4(), materials=(required,))
        )
''',
        '''    required = stale.model_copy(update={"required": True})
    required_service, *_ = _runtime(
        task=task,
        approved_materials=(required,),
    )
    with pytest.raises(ContextCompilerFreshnessError, match="fresh"):
        required_service.compile(
            _request(task=task, invocation_id=uuid4(), materials=(required,))
        )
''',
        label="stale required authority",
    )
    replace_once(
        path,
        '''    service, *_ = _runtime(task=task)
    result = service.compile(
        _request(task=task, invocation_id=uuid4(), materials=(private,))
    )
''',
        '''    service, *_ = _runtime(task=task, approved_materials=(private,))
    result = service.compile(
        _request(task=task, invocation_id=uuid4(), materials=(private,))
    )
''',
        label="private optional authority",
    )
    replace_once(
        path,
        '''    with pytest.raises(ContextCompilerPolicyError, match="required"):
        service.compile(
            _request(
                task=task,
                invocation_id=uuid4(),
                materials=(private.model_copy(update={"required": True}),),
            )
        )
''',
        '''    required_private = private.model_copy(update={"required": True})
    required_service, *_ = _runtime(
        task=task,
        approved_materials=(required_private,),
    )
    with pytest.raises(ContextCompilerPolicyError, match="required"):
        required_service.compile(
            _request(
                task=task,
                invocation_id=uuid4(),
                materials=(required_private,),
            )
        )
''',
        label="private required authority",
    )
    replace_once(
        path,
        '''    service, *_ = _runtime(task=task, policy=policy)
''',
        '''    service, *_ = _runtime(
        task=task,
        policy=policy,
        approved_materials=(long_evidence,),
    )
''',
        label="long evidence authority",
    )
    replace_once(
        path,
        '''    service, task, *_ = _runtime()
    invocation_id = uuid4()
''',
        '''    task = _task()
    invocation_id = uuid4()
''',
        label="conflict test task setup",
    )
    replace_once(
        path,
        '''    service.compile(
        _request(task=task, invocation_id=invocation_id, materials=(first,))
    )
''',
        '''    service, *_ = _runtime(
        task=task,
        approved_materials=(first, changed),
    )
    service.compile(
        _request(task=task, invocation_id=invocation_id, materials=(first,))
    )
''',
        label="conflict test approved materials",
    )
    replace_once(
        path,
        '''def test_required_stale_evidence_fails_and_optional_stale_is_reported() -> None:
''',
        '''def test_unapproved_material_is_rejected_before_compilation() -> None:
    service, task, *_ = _runtime()
    unapproved = _material(
        request_id=task.request_id,
        source_kind=ContextSourceKind.EVIDENCE,
        source_id="github.unapproved",
        content="unapproved evidence",
    )

    with pytest.raises(UnknownContextMaterialError, match="not approved"):
        service.compile(
            _request(task=task, invocation_id=uuid4(), materials=(unapproved,))
        )


def test_required_stale_evidence_fails_and_optional_stale_is_reported() -> None:
''',
        label="unapproved source acceptance test",
    )


def main() -> None:
    patch_compiler()
    patch_tests()


if __name__ == "__main__":
    main()
