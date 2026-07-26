# ADR 0016: Native typed specialist execution authority

- Status: Accepted
- Date: 2026-07-26
- Governing directive: `docs/SIMORGH_MASTER_DIRECTIVE.md`
- Parent implementation issue: #36
- Step issue: #40
- Implementation PR: #44

## Context

ADR 0013 established specialist definitions, deterministic routing and cost governance. ADR 0014 made task identity and routing state durable. ADR 0015 made model, tool and future specialist invocation identity, reservation, uncertainty and exact replay durable.

The remaining gap is execution of the already-selected specialist itself.

Without a native execution authority, later Voice, Notification, MCP, Work Graph, Channels or Delegation surfaces could accidentally:

- choose or replace a specialist after durable routing;
- widen tools, connectors, model tiers or mutation authority through natural language;
- execute under a budget different from the durable routed task;
- bypass the durable invocation store;
- repeat work after Core restart;
- claim model/tool cost directly instead of through governed gateways;
- expose private context or result content in failures and traces;
- confuse a local proposal with an externally verified side effect.

The first execution increment must prove the runtime itself without also introducing a live provider, connector, MCP server, mutation executor, new Android operation or public autonomous loop.

## Decision

Simorgh introduces one native, typed, zero-external specialist execution boundary.

### Authoritative inputs

A specialist execution request is derived from:

```text
Durable AgentTaskRecord in phase routed
RoutingDecision with exact agent ID and version
Compiled SpecialistDefinition
Stable invocation ID
Context-bundle fingerprint
Core-selected explicit capability subset
Durable task budget snapshot
```

It is not accepted as an unrestricted client-authored permission object.

### Request identity

`SpecialistExecutionRequest` binds:

```text
request_id
invocation_id
agent_id and exact version
task kind
execution mode and effect
input/output contract identity
canonical task fingerprint
context fingerprint and stable context_bundle_id
cancellation_owner_id
explicit capability subset
effective budget and monotonic timeout
stable creation identity
absolute deadline
attempt = 1
optional parent invocation identity without retry or delegation
```

Set-like task and capability fields are sorted before canonical hashing. Process-local current time is excluded from the durable invocation fingerprint.

Changing task, context, specialist version, capabilities, budget or output contract under the same invocation ID is an identity conflict.

### Capabilities

The capability set contains explicit subsets for:

```text
tool IDs
connector IDs
model tiers
proposal authority
future typed-mutation authority
```

Core derives the maximum from:

```text
specialist allowlists and model policy
∩ task allowed data sources
∩ execution mode
∩ specialist side-effect policy
```

The requested set must be a subset of that maximum.

The initial control plane does not accept client-selected capabilities. It creates only:

- an empty capability set for local read-only execution; or
- local proposal authority for a `propose_only` specialist.

A `typed_executor_only` policy is rejected. Mutation execution remains a separate reviewed trust boundary.

### Budget

The effective execution budget is:

```text
durable task budget limits
∩ original TaskEnvelope budget
∩ specialist budget ceiling
```

A cancelled, exhausted or widened durable budget is rejected before invocation execution.

The initial local proposal executor performs no model, tool or external call and commits zero direct usage.

A specialist result cannot claim model/tool usage directly. Future model/tool work must pass through the governed gateways and durable child invocation identities.

### Implementation registry

Native implementations are resolved by exact:

```text
(agent_id, agent_version)
```

Duplicate identities, unknown versions and output-contract mismatch fail closed.

Implementation availability is required only for a new invocation. Exact completed replay does not depend on the current in-process registry.

### Durable state and execution order

New execution:

```text
derive request from durable task and policy
    ↓
validate budget and capability subset
    ↓
InvocationStore.begin(kind=specialist)
    ↓
cancellation and deadline admission
    ↓
resolve exact implementation
    ↓
execute once
    ↓
validate typed result identity, payload and direct usage
    ↓
InvocationStore.complete
```

Completed replay:

```text
exact immutable identity match
    ↓
validate stored typed result and usage
    ↓
return replayed result
```

Replay performs zero new specialist, model, tool, connector or reservation calls. It may return after the original deadline or after removal of the implementation because no work is repeated.

### Result contract

`SpecialistExecutionResult` contains:

- task, invocation, specialist/version, effect and output-contract identity;
- typed terminal outcome;
- concrete bounded `SpecialistPlanPayload` for the Phase 1.3 completion family;
- typed evidence/artifact reference placeholders;
- direct committed usage;
- replay disposition;
- start/completion chronology;
- bounded reason for non-completed outcomes.

Inline payloads are limited to 256,000 canonical JSON bytes.

Evidence and artifact references are placeholders only. Durable artifact/result provenance is Phase 1 Step 1.4.

### Cancellation, expiry and uncertainty

- cancellation before implementation entry durably cancels the pending invocation;
- a cancelled parent budget blocks execution;
- an expired new invocation is durably expired before implementation entry;
- completed replay is not erased by later cancellation or deadline expiry;
- coroutine interruption before durable completion becomes `unknown` or `unknown_side_effect` according to effect class;
- no interrupted execution is automatically retried;
- cancellation tokens are bound to a stable per-invocation owner identity;
- absolute deadline and monotonic elapsed budget are checked before and after execution;
- full task-to-all-child cancellation enumeration remains Step 1.6.

### Control-plane exposure

The initial runtime is exposed through an internal Core control-plane method, not a public execution API.

The method accepts only:

```text
request_id
invocation_id
context fingerprint
```

It retrieves the durable task, resolves compiled policy, selects the zero-external capability set, manages an in-process cancellation token and delegates to the durable runtime.

The existing operator task API remains routing-only.

### Privacy and failure handling

- invocation-store failure prevents implementation entry;
- invalid result identity/schema becomes a durable failed invocation;
- implementation exception messages are not persisted;
- only typed failure codes and exception class names are retained;
- validation errors do not echo private payload content;
- prompt, context body, credentials, connector data, tool arguments/results, notification, audio and Accessibility trees are absent from failure metadata and traces.

### Initial implementation

The first executor is a deterministic local proposal fixture.

It validates:

- cancellation;
- request and budget identity;
- exact agent/version/output contract;
- proposal effect;
- typed bounded result.

It performs no network, provider, connector, MCP or Android side effect.

## Consequences

### Positive

- one already-selected specialist can execute through a Simorgh-native authority;
- permissions cannot be widened by client or model output;
- durable specialist completion replays across restart without duplicate execution or cost;
- local proposal execution proves the runtime at zero external cost;
- changed context/policy/budget under a reused invocation ID conflicts;
- cancellation, expiry and implementation failures become durable terminal facts;
- later model/tool specialists can reuse the same parent execution contract while child calls remain governed by existing gateways;
- later cancellation, trace and artifact steps receive stable ownership and result hooks.

### Negative

- the initial implementation is intentionally limited to local zero-external execution;
- the public API remains routing-only;
- the task record does not yet contain a final typed specialist-result phase;
- artifact/evidence references are not yet backed by a durable artifact store;
- full child-invocation cancellation and end-to-end trace are later steps;
- no live provider, connector or MCP validation occurs here;
- no mutation authority is added.

## Rejected alternatives

### Let the client submit a complete execution request

Rejected because the client could widen capabilities, budget, specialist version or output contract.

### Let the specialist choose its own tools or permissions

Rejected because model or implementation output is not authorization.

### Execute before durable invocation claim

Rejected because crash-safe replay and duplicate suppression would be impossible.

### Require the current implementation for completed replay

Rejected because durable completed truth must survive implementation removal or upgrade.

### Treat deadline expiry as invalidating completed replay

Rejected because replay repeats no work and the completed result is already authoritative.

### Permit native specialists to report model/tool cost directly

Rejected because that bypasses governed child gateways, reservations and provider/tool identity.

### Add a mutation executor in the same PR

Rejected because each mutation domain requires its own plan hash, approval, executor, verification and uncertainty boundary.

### Expose a public execution endpoint immediately

Rejected until application-lifespan configuration, implementation registry policy and operator-facing status semantics are finalized without fixture leakage.

### Use the invalid concurrent publisher archive

Rejected after an isolated audit showed the three staged parts produced invalid Base64 and no trustworthy product file could be extracted. No content from that archive was applied.

## Validation requirements

Before acceptance, automated tests must prove:

- strict request/result validation;
- task/policy-derived identity and stable hashing;
- tool/connector/model/mutation capability widening rejection;
- exact-version registry and duplicate rejection;
- budget intersection, widening, cancellation and exhaustion guards;
- deterministic zero-cost proposal result;
- cancellation and expiry before implementation entry;
- durable execute-once and exact replay;
- SQLite reopen replay after deadline and implementation removal;
- changed-context conflict;
- in-progress duplicate suppression;
- store failure prevents implementation entry;
- invalid result terminalization;
- direct model/tool cost-bypass rejection;
- private exception/payload content absent from durable failures;
- internal control-plane capability selection;
- active cancellation-token propagation;
- typed-mutation policy remains disabled;
- Core Ruff, strict MyPy and full tests;
- Android build, JVM tests, lint and APK;
- no live provider, connector or MCP call in ordinary CI;
- no unresolved review thread on the exact merge-candidate head.

## Follow-up

After ADR 0016 is accepted:

1. Step 1.4 defines durable typed results, evidence and artifact provenance;
2. Step 1.5 adds one governed read-only GitHub connector workflow;
3. Step 1.6 completes task-to-child cancellation propagation;
4. Step 1.7 adds bounded context compilation;
5. Step 1.8 adds durable end-to-end trace;
6. later Voice, Notification, MCP and Work Graph surfaces submit through these native authorities.
