from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: str, old: str, new: str, *, count: int = 1) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if text.count(old) != count:
        raise RuntimeError(f"expected {count} exact anchor(s) in {path}")
    target.write_text(text.replace(old, new), encoding="utf-8")


contracts = "services/core/src/simorgh_core/agents/contracts.py"
defaults = "services/core/src/simorgh_core/agents/defaults.py"
cli = "services/core/src/simorgh_core/agents/live_provider_staging_cli.py"
children = "services/core/src/simorgh_core/agents/trace_child_invocations.py"
reconciliation = "services/core/src/simorgh_core/agents/trace_reconciliation.py"
child_tests = "services/core/tests/test_trace_child_invocations.py"
cli_tests = "services/core/tests/test_live_provider_staging_cli.py"
validation = "docs/validation/phase-1-9-manual-staging-boundary.md"

replace_exact(
    contracts,
    '''class TaskKind(StrEnum):
    REPOSITORY_RESEARCH = "repository_research"
    DEVELOPMENT_PLANNING = "development_planning"
''',
    '''class TaskKind(StrEnum):
    REPOSITORY_RESEARCH = "repository_research"
    LIVE_PROVIDER_STAGING = "live_provider_staging"
    DEVELOPMENT_PLANNING = "development_planning"
''',
)

replace_exact(
    defaults,
    '''_PLANNING_BUDGET = TaskBudget(
    max_model_calls=2,
''',
    '''_LIVE_PROVIDER_STAGING_BUDGET = TaskBudget(
    max_model_calls=1,
    max_tool_calls=0,
    max_input_tokens=128,
    max_output_tokens=16,
    max_estimated_cost_microusd=20_000,
    max_elapsed_ms=60_000,
    max_retries=0,
    max_parallel_branches=1,
)
_PLANNING_BUDGET = TaskBudget(
    max_model_calls=2,
''',
)
replace_exact(
    defaults,
    '''_PLANNING_MODEL_POLICY = ModelPolicy(
    allowed_tiers=(ModelTier.FAST, ModelTier.GENERAL, ModelTier.REASONING),
''',
    '''_LIVE_PROVIDER_STAGING_MODEL_POLICY = ModelPolicy(
    allowed_tiers=(ModelTier.FAST,),
    minimum_tier=ModelTier.FAST,
    maximum_model_calls=1,
)
_PLANNING_MODEL_POLICY = ModelPolicy(
    allowed_tiers=(ModelTier.FAST, ModelTier.GENERAL, ModelTier.REASONING),
''',
)
replace_exact(
    defaults,
    '''def default_specialist_definitions() -> tuple[SpecialistDefinition, ...]:
    return (
        SpecialistDefinition(
            agent_id="github.read",
''',
    '''def default_specialist_definitions() -> tuple[SpecialistDefinition, ...]:
    return (
        SpecialistDefinition(
            agent_id="system.live-provider-staging",
            version="1.0.0",
            display_name="Protected Live Provider Staging Agent",
            task_kinds=frozenset({TaskKind.LIVE_PROVIDER_STAGING}),
            locale_prefixes=frozenset({"en"}),
            input_contract="simorgh.task.v1",
            output_contract="simorgh.live-provider-staging.v1",
            tool_allowlist=frozenset(),
            connector_allowlist=frozenset(),
            model_policy=_LIVE_PROVIDER_STAGING_MODEL_POLICY,
            budget_ceiling=_LIVE_PROVIDER_STAGING_BUDGET,
            side_effect_policy=SideEffectPolicy.NONE,
            routing_rules=(),
            routing_priority=5,
        ),
        SpecialistDefinition(
            agent_id="github.read",
''',
)

replace_exact(
    cli,
    '''        explicit_task_kind=TaskKind.DEVELOPMENT_PLANNING,
''',
    '''        explicit_task_kind=TaskKind.LIVE_PROVIDER_STAGING,
''',
)
replace_exact(
    cli,
    '''    id_factory: Callable[[], UUID] = uuid4,
    propagate_internal_errors: bool = False,
) -> LiveProviderStagingArtifact:
''',
    '''    id_factory: Callable[[], UUID] = uuid4,
) -> LiveProviderStagingArtifact:
''',
)
replace_exact(
    cli,
    '''            except BaseException:
                if propagate_internal_errors:
                    raise
                failure_code = LiveProviderStagingArtifactFailureCode.EXECUTION_FAILED
''',
    '''            except BaseException:
                failure_code = LiveProviderStagingArtifactFailureCode.EXECUTION_FAILED
''',
)
replace_exact(
    cli,
    '''                except Exception:
                    if propagate_internal_errors:
                        raise
                    failure_code = LiveProviderStagingArtifactFailureCode.TRACE_INVALID
''',
    '''                except Exception:
                    failure_code = LiveProviderStagingArtifactFailureCode.TRACE_INVALID
''',
)
replace_exact(
    cli,
    '''                    except BaseException:
                        if propagate_internal_errors:
                            raise
                        failure_code = (
''',
    '''                    except BaseException:
                        failure_code = (
''',
)
replace_exact(
    cli,
    '''    except BaseException:
        if propagate_internal_errors:
            raise
        failure_code = LiveProviderStagingArtifactFailureCode.EXECUTION_FAILED
''',
    '''    except BaseException:
        failure_code = LiveProviderStagingArtifactFailureCode.EXECUTION_FAILED
''',
)
replace_exact(
    cli_tests,
    '''        id_factory=ids.__next__,
        propagate_internal_errors=True,
''',
    '''        id_factory=ids.__next__,
''',
    count=2,
)

replace_exact(
    children,
    '''from simorgh_core.agents.contracts import InvocationState
''',
    '''from simorgh_core.agents.contracts import InvocationState, RoutingState
''',
)
replace_exact(
    children,
    '''def project_specialist_owned_child_invocations(
''',
    '''def project_routed_root_invocations(
    *,
    store: TraceStore,
    task_entry: AgentTaskStoreEntryV1,
    routing_event: TraceEventRecord,
    invocation_records: tuple[InvocationRecord, ...],
    base_ingested_at_ms: int,
) -> ChildTraceProjectionReport:
    """Project root model/tool calls owned by the exact routed specialist."""

    decision = task_entry.record.routing_decision
    if (
        decision is None
        or decision.state != RoutingState.ROUTED
        or decision.selected_agent_id is None
        or decision.selected_agent_version is None
    ):
        return _empty_report()
    direct = tuple(
        record
        for record in invocation_records
        if record.request_id == task_entry.request_id
        and record.kind in {InvocationKind.MODEL, InvocationKind.TOOL}
        and record.parent_invocation_id is None
        and record.cancellation_owner_id is None
        and record.agent_id == decision.selected_agent_id
        and record.agent_version == decision.selected_agent_version
        and record.invocation_id != decision.classifier_invocation_id
    )
    return _project_invocation_chain(
        store=store,
        records=direct,
        root_parent_event=routing_event,
        root_parent_invocation_id=None,
        base_ingested_at_ms=base_ingested_at_ms,
    )


def project_specialist_owned_child_invocations(
''',
)
replace_exact(
    children,
    '''    "project_classifier_invocation",
    "project_specialist_owned_child_invocations",
''',
    '''    "project_classifier_invocation",
    "project_routed_root_invocations",
    "project_specialist_owned_child_invocations",
''',
)

replace_exact(
    reconciliation,
    '''    ChildTraceProjectionReport,
    project_classifier_invocation,
    project_specialist_owned_child_invocations,
''',
    '''    ChildTraceProjectionReport,
    project_classifier_invocation,
    project_routed_root_invocations,
    project_specialist_owned_child_invocations,
''',
)
replace_exact(
    reconciliation,
    '''    context_events, contexts_by_invocation = _project_contexts(
''',
    '''    direct_report = project_routed_root_invocations(
        store=store,
        task_entry=entry,
        routing_event=routing,
        invocation_records=invocations,
        base_ingested_at_ms=counter.current_ingestion_time(),
    )
    counter.absorb(direct_report)

    context_events, contexts_by_invocation = _project_contexts(
''',
)

replace_exact(
    child_tests,
    '''    project_classifier_invocation,
    project_specialist_owned_child_invocations,
''',
    '''    project_classifier_invocation,
    project_routed_root_invocations,
    project_specialist_owned_child_invocations,
''',
)
replace_exact(
    child_tests,
    '''def _task_entry(
    request_id: UUID,
    *,
    classifier_invocation_id: UUID | None = None,
) -> AgentTaskStoreEntryV1:
    decision = type(
        "Decision",
        (),
        {"classifier_invocation_id": classifier_invocation_id},
    )()
''',
    '''def _task_entry(
    request_id: UUID,
    *,
    classifier_invocation_id: UUID | None = None,
    selected_agent_id: str = "development.planner",
    selected_agent_version: str = "1.0.0",
) -> AgentTaskStoreEntryV1:
    decision = type(
        "Decision",
        (),
        {
            "classifier_invocation_id": classifier_invocation_id,
            "state": RoutingState.ROUTED,
            "selected_agent_id": selected_agent_id,
            "selected_agent_version": selected_agent_version,
        },
    )()
''',
)
replace_exact(
    child_tests,
    '''def test_specialist_owned_tool_is_linked_by_unique_cancellation_owner() -> None:
''',
    '''def test_direct_routed_model_is_linked_to_routing_and_unrelated_root_is_ignored() -> None:
    request_id = uuid4()
    selected_id = uuid4()
    unrelated_id = uuid4()
    trace_store = InMemoryTraceStore()
    task_event = _task_claim(trace_store, request_id)
    decision_id = uuid4()
    routing = trace_store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.ROUTING_DECIDED,
            stage=TraceStage.ROUTING,
            source_authority_kind=TraceSourceAuthorityKind.ROUTING_DECISION,
            source_authority_id=decision_id,
            source_authority_sha256=_SHA_B,
            parent_event_id=task_event.event_id,
            causation_event_id=task_event.event_id,
            details=TraceRoutingDetails(
                routing_fingerprint=_SHA_B,
                state=RoutingState.ROUTED,
                method=RoutingMethod.EXPLICIT_TASK_KIND,
                selected_agent_id="system.live-provider-staging",
                selected_agent_version="1.0.0",
            ),
            occurred_at_ms=1_100,
        ),
        ingested_at_ms=2_100,
    ).record
    invocation_store = InMemoryInvocationStore(wall_clock_millis=lambda: 1_500)
    invocation_store.begin(
        invocation_id=selected_id,
        request_id=request_id,
        agent_id="system.live-provider-staging",
        agent_version="1.0.0",
        operation="avalai-live-canary",
        input_fingerprint=_SHA_A,
        kind=InvocationKind.MODEL,
        effect=InvocationEffect.READ_ONLY,
        provider_id="avalai",
        model_id="gpt-5.4-mini",
    )
    unrelated = invocation_store.begin(
        invocation_id=unrelated_id,
        request_id=request_id,
        agent_id="another.agent",
        agent_version="1.0.0",
        operation="unrelated-model",
        input_fingerprint=_SHA_B,
        kind=InvocationKind.MODEL,
        effect=InvocationEffect.READ_ONLY,
        provider_id="avalai",
        model_id="gpt-5.4-mini",
    ).record
    usage = UsageVector(model_calls=1, input_tokens=8, output_tokens=2)
    invocation_store.reserve(invocation_id=selected_id, usage=usage)
    invocation_store.complete(
        invocation_id=selected_id,
        result_payload={"text_sha256": _SHA_C},
        committed_usage=usage,
    )
    selected = invocation_store.get(selected_id)

    report = project_routed_root_invocations(
        store=trace_store,
        task_entry=_task_entry(
            request_id,
            selected_agent_id="system.live-provider-staging",
        ),
        routing_event=routing,
        invocation_records=(selected, unrelated),
        base_ingested_at_ms=3_000,
    )
    selected_events = tuple(
        event
        for event in trace_store.view(request_id).events
        if event.invocation_id == selected_id
    )

    assert report.projected_event_count == 2
    assert selected_events[0].parent_event_id == routing.event_id
    assert selected_events[0].stage == TraceStage.MODEL
    assert selected_events[1].usage == usage
    assert all(
        event.invocation_id != unrelated_id
        for event in trace_store.view(request_id).events
    )


def test_specialist_owned_tool_is_linked_by_unique_cancellation_owner() -> None:
''',
)

replace_exact(
    validation,
    '''The CLI enters the existing Core lifespan and therefore reuses the native:
''',
    '''The CLI first persists and routes a fixed read-only `TaskEnvelope` with the
explicit `live_provider_staging` task kind to the internal
`system.live-provider-staging` specialist. It then enters the existing Core
lifespan and reuses the native:
''',
)
replace_exact(
    validation,
    '''It does not create a parallel invocation, budget, Trace or result authority.
''',
    '''It does not create a parallel invocation, budget, Trace or result authority.
Trace reconciliation projects a root model/tool invocation only when its agent
and version exactly match the durable routing decision, it has no parent or
specialist cancellation owner, and it is not the router classifier invocation.
''',
)

print("Phase 1.9 direct routed invocation trace candidate applied.")
