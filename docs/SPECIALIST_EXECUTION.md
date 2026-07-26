# Simorgh specialist execution runtime

Status: Phase 1 Step 1.3 merged through PR #44 at `2bc113a29960a1935db3f91c27cb6863f0ac35b5`; issue #40 is complete and ADR 0016 is accepted. Its separate typed result authority merged through Phase 1.4 PR #48 at `98d56689df4442541e30c77451ab56550e473479`; issue #46 is complete and ADR 0017 is accepted.

This runtime executes exactly one specialist that has already been selected by the durable routing control plane. It does not route a task, discover permissions, connect to external systems, or authorize a side effect.

## Authority boundary

```text
durable routed TaskEnvelope
    ↓
compiled SpecialistDefinition
    ↓
derived SpecialistExecutionRequest
    ↓
exact-version native SpecialistExecutor
    ↓
typed SpecialistExecutionResult
    ↓
durable InvocationStore(kind=specialist)
    ↓ Phase 1.4 exact cross-authority terminalization
immutable ResultStore authority
```

Simorgh Core remains the authority for:

- task and invocation identity;
- specialist identity and exact version;
- task kind and execution mode;
- capability and budget intersection;
- cancellation and deadline admission;
- execution-result contract and durable invocation completion;
- final result-schema admission and immutable result claim;
- replay and terminal uncertainty.

A model, Skill, connector, MCP server, channel, Android node, or specialist implementation cannot widen these fields.

## Derived request

`SpecialistExecutionRequest` is built from:

```text
TaskEnvelope
RoutingDecision
SpecialistDefinition
stable invocation_id
context fingerprint
explicit requested capability subset
```

It is not accepted as an unrestricted client-authored permission object.

The request binds:

- request and invocation IDs;
- exact agent ID and semantic version;
- resolved task kind;
- execution mode and invocation effect;
- input and output contract identities;
- canonical task fingerprint;
- context-bundle fingerprint and stable `context_bundle_id`;
- stable per-invocation `cancellation_owner_id`;
- explicit capability subset;
- effective budget and its monotonic timeout after task/policy intersection;
- stable creation identity and absolute deadline;
- optional parent invocation identity without enabling retry or delegation.

Task fingerprints sort set-like data-source identities before hashing so the same typed task remains stable across processes.

## Capability subset

The capability object contains typed subsets for:

```text
tool IDs
connector IDs
model tiers
proposal authority
future typed-mutation authority
```

The requested subset must be contained in the maximum derived from:

```text
specialist tool allowlist
specialist connector allowlist ∩ task allowed_data_sources
specialist model policy
specialist side-effect policy
current execution mode
```

Capabilities are explicit. A proposal specialist must receive explicit proposal authority. Typed mutation authority is accepted only for `execute_typed` and a `typed_executor_only` policy. No mutation executor is registered by this work.

## Effective budget

The execution budget is:

```text
request TaskBudget ∩ specialist budget ceiling
```

The runtime rejects a `BudgetAccount` whose request identity or limits differ from the derived request.

The deterministic proposal fixture consumes:

```text
model calls = 0
tool calls = 0
tokens = 0
estimated cost = 0
```

A native specialist result cannot claim model or tool usage directly. Future model/tool work must pass through the governed gateways and their own durable child invocation identities.

## Implementation registry

`SpecialistExecutorRegistry` is keyed by the exact tuple:

```text
(agent_id, agent_version)
```

It rejects duplicate implementations, unknown versions, and output contracts that differ from the compiled specialist policy.

Completed replay does not depend on the current in-process executor registry. If an implementation is removed after a successful invocation, the exact durable execution result can still replay.

## Execution result contract

`SpecialistExecutionResult` contains:

- request, invocation, agent, version, effect, and output-contract identity;
- typed terminal outcome;
- concrete bounded `SpecialistPlanPayload` for completed Phase 1.3 results;
- zero or more typed evidence/artifact reference placeholders at the execution layer;
- committed direct usage;
- replay disposition;
- start and completion chronology;
- bounded reason for non-completed outcomes.

Inline execution payloads are limited to 256,000 canonical JSON bytes. Arbitrary final dictionaries, raw model text, Python objects, raw connector responses, and private validation values are rejected.

Phase 1.4 PR #48 replaces the placeholder boundary with durable artifact/evidence metadata references and one immutable typed result authority. Artifact bytes and raw source bodies remain outside that authority. See [`TYPED_RESULTS.md`](TYPED_RESULTS.md).

## Durable execution and replay

For a new invocation:

```text
derive and validate request
    ↓
validate parent budget identity
    ↓
durable pending specialist invocation claim
    ↓
cancellation and deadline admission
    ↓
resolve exact executor implementation
    ↓
execute once
    ↓
validate typed result and zero direct external usage
    ↓
durable completed invocation result
```

For a completed invocation:

```text
exact immutable identity match
    ↓
validate stored typed execution result and usage
    ↓
return replayed execution result
```

Invocation replay performs no executor, model, tool, connector, or budget-reservation call.

Invocation fingerprints exclude process-local execution creation time but include task, context, capability, policy, budget, and target identity. Changing context or permissions under the same invocation ID conflicts.

## Phase 1.4 final result terminalization

After a completed specialist invocation, the Phase 1.4 terminalizer:

```text
loads the durable invocation
    ↓
requires kind=specialist and state=completed
    ↓
validates exact execution payload and committed usage
    ↓
resolves exact result schema/version
    ↓
constructs canonical typed result + reference metadata
    ↓
claims one immutable ResultStore record
```

Final result replay returns the stored result ID and canonical SHA-256 without re-entering the specialist, adding usage, changing privacy/retention, or replacing artifact/evidence metadata.

The invocation store remains execution-recovery authority. The result store is the final typed-result authority. If result persistence fails, Phase 1.4 claims no success even though the Phase 1.3 invocation may already be completed and available for a later idempotent terminalization attempt.

## Cancellation and deadlines

- cancellation tokens are bound to the request’s stable owner identity;
- cancellation before executor entry durably cancels the pending specialist invocation;
- a cancelled parent `BudgetAccount` blocks execution;
- an expired new invocation is durably expired before executor entry;
- monotonic elapsed budget is checked before and after executor execution;
- cancellation after durable completion does not erase a completed replay;
- completed replay can be returned after the original deadline because no work is re-executed;
- coroutine interruption before durable completion becomes `unknown` or `unknown_side_effect` according to effect class;
- no interrupted invocation is automatically retried.

Full task-to-all-child ownership enumeration and adapter cancellation remain Phase 1 Step 1.6.

## Failure and privacy behavior

- invocation-store failure prevents specialist entry;
- invalid execution-result identity or schema becomes a durable failed invocation;
- direct nonzero model/tool usage is rejected;
- implementation exception messages are not persisted;
- only bounded exception class and typed failure code are stored;
- result-store failure prevents Phase 1.4 success;
- changed final payload/reference metadata under one invocation identity conflicts;
- result payload/hash/index corruption latches the result authority unhealthy;
- no raw prompt, context bundle, credentials, tool arguments/results, source body, artifact bytes, presentation text, notification, audio, or Accessibility tree enters failure metadata or traces.

If durable invocation completion fails after the implementation returned, the runtime claims no success and attempts to mark the invocation unknown. If the invocation store itself is unhealthy, startup recovery remains authoritative.

If final result persistence fails after durable invocation completion, no Phase 1.4 success is returned. The completed invocation is not erased or charged again and may be terminalized idempotently once the result authority is healthy.

## Initial implementation

The first implementation is a deterministic `StaticProposalSpecialistExecutor` used to validate the runtime with no network, model, connector, MCP, or Android side effect.

It checks:

- cancellation;
- request/budget identity;
- exact executor identity and output contract;
- proposal effect;
- typed bounded result construction.

The first final result family is `simorgh.specialist-plan-result` schema `1.0`, bound to output contract `simorgh.typed-plan.v1`.

## Automated validation

The Phase 1.3 test slice covers:

- task/policy-derived request construction;
- stable task fingerprinting;
- capability widening rejection;
- explicit proposal authority;
- wrong route version rejection;
- exact-version executor lookup and duplicate rejection;
- cancellation before entry;
- zero-cost typed proposal output;
- private invalid payload rejection;
- execute-once and exact invocation replay;
- SQLite invocation reopen replay;
- invocation replay after deadline and executor removal;
- changed-context conflict;
- durable cancellation and expiry;
- invocation-store failure before executor entry;
- invalid execution-result terminalization;
- direct cost-bypass rejection;
- exception-message sanitization;
- stable specialist invocation fingerprinting;
- concrete plan-payload validation and arbitrary-field rejection;
- stable context-bundle and cancellation-owner identities;
- wrong cancellation-owner rejection;
- monotonic expiry before and during execution;
- privacy-safe specialist start/completion/failure/replay traces.

The Phase 1.4 test slice adds:

- exact result registry and duplicate/unknown rejection;
- raw/arbitrary final payload rejection;
- stable canonical result hash and presentation independence;
- artifact size/hash/media/storage validation;
- evidence taint, freshness and artifact-link validation;
- conservative privacy and retention composition;
- in-memory and SQLite final-result replay;
- restart replay with identical result ID/hash and no usage rewrite;
- changed payload/reference conflicts;
- durable invocation payload/usage cross-check;
- SQLite corruption, schema and concurrent-owner failures;
- application lifespan and distinct-store-path validation;
- private payload absence from errors and result traces.

Ordinary CI must remain fake/local and cost-free.

## Current limitations

- the runtime is not yet exposed through an operator execution or result API;
- the agent-task record has not yet gained a specialist execution/result phase;
- only deterministic local proposal execution is implemented;
- only the typed-plan final result family is registered;
- model-backed specialists and governed tools are not enabled here;
- typed artifact/evidence metadata persistence is implemented in Phase 1.4 PR #48, but production artifact-byte storage is not;
- no connector, MCP server, mutation executor, Android operation, Voice, Notification, Memory, Work Graph, Delegation, or retry API is added;
- end-to-end durable tracing remains later Phase 1 work;
- no physical Samsung Galaxy A53 validation is claimed.
