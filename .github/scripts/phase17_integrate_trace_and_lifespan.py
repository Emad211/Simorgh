from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, *, label: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: count={count}, expected=1")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_tracing() -> None:
    path = "services/core/src/simorgh_core/agents/tracing.py"
    replace_once(
        path,
        '''    CANCELLATION_SETTLED = "cancellation_settled"
    CANCELLATION_REPLAYED = "cancellation_replayed"
    RESULT_FAILED = "result_failed"
''',
        '''    CANCELLATION_SETTLED = "cancellation_settled"
    CANCELLATION_REPLAYED = "cancellation_replayed"
    CONTEXT_COMPILED = "context_compiled"
    CONTEXT_REPLAYED = "context_replayed"
    CONTEXT_FAILED = "context_failed"
    RESULT_FAILED = "result_failed"
''',
        label="context trace event kinds",
    )


def patch_context_store() -> None:
    path = "services/core/src/simorgh_core/agents/context_store.py"
    replace_once(
        path,
        '''def _validated_fresh_record(record: SpecialistContextBundle) -> SpecialistContextBundle:
''',
        '''class ContextStoreRegistry:
    """Process-wide context authority configured once per Core lifespan."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: ContextStore = InMemoryContextStore()

    def current(self) -> ContextStore:
        with self._lock:
            return self._store

    def configure(self, store: ContextStore) -> None:
        store.load()
        with self._lock:
            previous = self._store
            self._store = store
        if previous is not store:
            previous.close()

    def reset_to_memory(self) -> None:
        replacement = InMemoryContextStore()
        with self._lock:
            previous = self._store
            self._store = replacement
        previous.close()


context_store_registry = ContextStoreRegistry()


def _validated_fresh_record(record: SpecialistContextBundle) -> SpecialistContextBundle:
''',
        label="context store process registry",
    )
    replace_once(
        path,
        '''    "ContextStoreInUseError",
    "ContextStoreSchemaError",
''',
        '''    "ContextStoreInUseError",
    "ContextStoreRegistry",
    "ContextStoreSchemaError",
''',
        label="context registry export",
    )
    replace_once(
        path,
        '''    "SQLiteContextStore",
]
''',
        '''    "SQLiteContextStore",
    "context_store_registry",
]
''',
        label="context store singleton export",
    )


def patch_config() -> None:
    path = "services/core/src/simorgh_core/config.py"
    replace_once(
        path,
        '''    simorgh_result_store_path: str = Field(
        default=".simorgh/results.sqlite3",
        min_length=1,
        max_length=4_096,
    )

    avalai_api_key: SecretStr | None = None
''',
        '''    simorgh_result_store_path: str = Field(
        default=".simorgh/results.sqlite3",
        min_length=1,
        max_length=4_096,
    )
    simorgh_context_store_path: str = Field(
        default=".simorgh/contexts.sqlite3",
        min_length=1,
        max_length=4_096,
    )

    avalai_api_key: SecretStr | None = None
''',
        label="context store setting",
    )


def patch_app() -> None:
    path = "services/core/src/simorgh_core/app.py"
    replace_once(
        path,
        '''from simorgh_core.agents.invocation_store import (
''',
        '''from simorgh_core.agents.context_store import (
    SQLiteContextStore,
    context_store_registry,
)
from simorgh_core.agents.invocation_store import (
''',
        label="context store app imports",
    )
    replace_once(
        path,
        '''        "results": settings.simorgh_result_store_path,
    }
''',
        '''        "results": settings.simorgh_result_store_path,
        "contexts": settings.simorgh_context_store_path,
    }
''',
        label="distinct context path",
    )
    replace_once(
        path,
        '''                    "Core durable task, invocation, result, and Android action store paths "
''',
        '''                    "Core durable task, invocation, result, context, and Android action "
                    "store paths "
''',
        label="distinct store error detail",
    )
    replace_once(
        path,
        '''    invocation_store: SQLiteInvocationStore | None = None
    result_store: SQLiteResultStore | None = None
''',
        '''    invocation_store: SQLiteInvocationStore | None = None
    result_store: SQLiteResultStore | None = None
    context_store: SQLiteContextStore | None = None
''',
        label="context lifespan variable",
    )
    replace_once(
        path,
        '''    invocation_store_configured = False
    result_store_configured = False
''',
        '''    invocation_store_configured = False
    result_store_configured = False
    context_store_configured = False
''',
        label="context lifespan flag",
    )
    replace_once(
        path,
        '''        result_store = SQLiteResultStore(settings.simorgh_result_store_path)
        action_journal = SQLiteActionJournal(
''',
        '''        result_store = SQLiteResultStore(settings.simorgh_result_store_path)
        context_store = SQLiteContextStore(settings.simorgh_context_store_path)
        action_journal = SQLiteActionJournal(
''',
        label="open context authority",
    )
    replace_once(
        path,
        '''        result_store_registry.configure(result_store)
        result_store_configured = True
''',
        '''        result_store_registry.configure(result_store)
        result_store_configured = True
        context_store_registry.configure(context_store)
        context_store_configured = True
''',
        label="configure context authority",
    )
    replace_once(
        path,
        '''    except BaseException:
        if result_store_configured:
''',
        '''    except BaseException:
        if context_store_configured:
            context_store_registry.reset_to_memory()
        elif context_store is not None:
            context_store.close()
        if result_store_configured:
''',
        label="context startup rollback",
    )
    replace_once(
        path,
        '''    finally:
        try:
            result_store_registry.reset_to_memory()
        finally:
            try:
                invocation_store_registry.reset_to_memory()
''',
        '''    finally:
        try:
            context_store_registry.reset_to_memory()
        finally:
            try:
                result_store_registry.reset_to_memory()
            finally:
                try:
                    invocation_store_registry.reset_to_memory()
''',
        label="context shutdown reset",
    )
    replace_once(
        path,
        '''            finally:
                try:
                    await agent_task_control_plane.reset_to_memory_store()
                finally:
                    await action_broker.reset_to_memory_journal()
''',
        '''                finally:
                    try:
                        await agent_task_control_plane.reset_to_memory_store()
                    finally:
                        await action_broker.reset_to_memory_journal()
''',
        label="lifespan nested cleanup indentation",
    )


def patch_compiler() -> None:
    path = "services/core/src/simorgh_core/agents/context_compiler.py"
    replace_once(
        path,
        '''from simorgh_core.agents.task_store import AgentTaskStore
''',
        '''from simorgh_core.agents.task_store import AgentTaskStore
from simorgh_core.agents.tracing import (
    CacheDisposition,
    NullTraceSink,
    TraceEventKind,
    TraceSink,
    trace_event,
)
''',
        label="context trace imports",
    )
    replace_once(
        path,
        '''        policy: ContextCompilerPolicy | None = None,
        wall_clock_millis: Callable[[], int] | None = None,
''',
        '''        policy: ContextCompilerPolicy | None = None,
        trace_sink: TraceSink | None = None,
        wall_clock_millis: Callable[[], int] | None = None,
''',
        label="context trace constructor",
    )
    replace_once(
        path,
        '''        self._policy = policy or ContextCompilerPolicy()
        self._wall_clock_millis = wall_clock_millis or (
''',
        '''        self._policy = policy or ContextCompilerPolicy()
        self._trace_sink = trace_sink or NullTraceSink()
        self._wall_clock_millis = wall_clock_millis or (
''',
        label="context trace sink assignment",
    )
    replace_once(
        path,
        '''    def compile(self, request: ContextCompilationRequest) -> ContextCompilationResult:
        if not self._policy.enabled:
            raise ContextCompilerDisabledError("context compiler is disabled")
        now_ms = self._now_ms()
''',
        '''    def compile(self, request: ContextCompilationRequest) -> ContextCompilationResult:
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
''',
        label="context compile trace wrapper",
    )
    replace_once(
        path,
        '''    def _now_ms(self) -> int:
        return max(0, int(self._wall_clock_millis()))
''',
        '''    def _emit_result(self, result: ContextCompilationResult) -> None:
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
''',
        label="context trace emitters",
    )


def patch_context_tests() -> None:
    path = "services/core/tests/test_context_compiler.py"
    replace_once(
        path,
        '''from simorgh_core.agents.task_store import (
    InMemoryAgentTaskStore,
    new_task_store_entry,
)
''',
        '''from simorgh_core.agents.task_store import (
    InMemoryAgentTaskStore,
    new_task_store_entry,
)
from simorgh_core.agents.tracing import InMemoryTraceSink, TraceEventKind
''',
        label="context trace test imports",
    )
    replace_once(
        path,
        '''    approved_materials: tuple[ContextMaterial, ...] = (),
) -> tuple[
''',
        '''    approved_materials: tuple[ContextMaterial, ...] = (),
    trace_sink: InMemoryTraceSink | None = None,
) -> tuple[
''',
        label="context trace test runtime input",
    )
    replace_once(
        path,
        '''        policy=policy,
        wall_clock_millis=lambda: _NOW_MS,
''',
        '''        policy=policy,
        trace_sink=trace_sink,
        wall_clock_millis=lambda: _NOW_MS,
''',
        label="context trace test runtime binding",
    )
    replace_once(
        path,
        '''def _cancellation(task: TaskEnvelope, *, version: int = 0) -> TaskCancellationRequest:
''',
        '''def test_context_trace_contains_only_bounded_authority_metadata() -> None:
    task = _task()
    marker = "PRIVATE_CONTEXT_MARKER_9d1f"
    evidence = _material(
        request_id=task.request_id,
        source_kind=ContextSourceKind.EVIDENCE,
        source_id="github.trace",
        content=marker,
    )
    trace = InMemoryTraceSink()
    service, *_ = _runtime(
        task=task,
        approved_materials=(evidence,),
        trace_sink=trace,
    )
    request = _request(
        task=task,
        invocation_id=uuid4(),
        materials=(evidence,),
    )

    service.compile(request)
    service.compile(request)
    events = trace.for_request(task.request_id)
    serialized = repr([event.model_dump(mode="json") for event in events])

    assert [event.kind for event in events] == [
        TraceEventKind.CONTEXT_COMPILED,
        TraceEventKind.CONTEXT_REPLAYED,
    ]
    assert marker not in serialized
    assert events[0].metadata["section_count"] == 2
    assert events[0].metadata["tainted"] is True
    assert "context_sha256" in events[0].metadata


def test_context_failure_trace_redacts_material_and_exception_content() -> None:
    task = _task()
    marker = "FAILED_CONTEXT_MARKER_b72e"
    unapproved = _material(
        request_id=task.request_id,
        source_kind=ContextSourceKind.EVIDENCE,
        source_id="github.failed-trace",
        content=marker,
    )
    trace = InMemoryTraceSink()
    service, *_ = _runtime(task=task, trace_sink=trace)

    with pytest.raises(UnknownContextMaterialError):
        service.compile(
            _request(
                task=task,
                invocation_id=uuid4(),
                materials=(unapproved,),
            )
        )

    events = trace.for_request(task.request_id)
    serialized = repr([event.model_dump(mode="json") for event in events])
    assert len(events) == 1
    assert events[0].kind == TraceEventKind.CONTEXT_FAILED
    assert events[0].reason == "UnknownContextMaterialError"
    assert marker not in serialized


def _cancellation(task: TaskEnvelope, *, version: int = 0) -> TaskCancellationRequest:
''',
        label="context trace acceptance tests",
    )


def main() -> None:
    patch_tracing()
    patch_context_store()
    patch_config()
    patch_app()
    patch_compiler()
    patch_context_tests()


if __name__ == "__main__":
    main()
