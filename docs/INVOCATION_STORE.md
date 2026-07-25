# Durable invocation store

Status: implemented for governed model and structured read-tool calls in PR #39. The same contract is reserved for future specialist execution.

This store is the native authority for one external or specialist invocation identity. It is separate from:

- the agent-task store;
- the Android action journal;
- traces;
- the Personal Work Graph;
- long-term memory and artifacts.

## Configuration

```text
SIMORGH_INVOCATION_STORE_PATH=.simorgh/invocations.sqlite3
```

Use `:memory:` only in isolated tests. One active Simorgh Core process must own one invocation-store path. Distributed leases and multi-process writers are not supported in this increment.

## SQLite guarantees

The production store enables:

```text
PRAGMA foreign_keys = ON
PRAGMA busy_timeout = 5000
PRAGMA journal_mode = WAL
PRAGMA synchronous = FULL
```

Every row contains canonical JSON plus SHA-256. Indexed identity and state columns are compared against the decoded payload on load.

Core fails closed on:

- unsupported schema;
- failed SQLite integrity check;
- payload-hash mismatch;
- invalid typed payload;
- indexed columns that disagree with the payload;
- illegal or backward state transition;
- immutable identity/result/failure changes;
- a durable database operation failure.

The first durable store failure latches that store instance unhealthy. Later reads and writes do not fall back to stale memory.

## Immutable invocation identity

An invocation binds:

```text
invocation_id
request_id
agent_id and agent_version
operation
input_fingerprint
kind
side-effect class
provider/model or tool/connector target
parent_invocation_id
attempt
created_at_ms
```

Kinds:

```text
model
tool
specialist
```

Effects:

```text
read_only
proposal
mutation
```

Reusing an `invocation_id` with any changed immutable field is a conflict.

Input content is not stored by the invocation store. Only the canonical SHA-256 fingerprint is retained. The parent task store may separately retain the explicit `TaskEnvelope` text.

## State machine

```text
pending
    ├── reserved
    ├── completed
    ├── failed
    ├── cancelled
    ├── expired
    └── unknown / unknown_side_effect

reserved
    ├── completed
    ├── failed
    └── unknown / unknown_side_effect
```

Terminal states:

```text
completed
failed
cancelled
expired
unknown
unknown_side_effect
```

A terminal invocation identity cannot be reused as a new attempt.

## Pre-call ordering

The model and tool gateways use this order:

```text
policy and target selection
    ↓
durable pending invocation claim
    ↓
request-budget reservation
    ↓
durable invocation reservation
    ↓
external provider/tool call
```

The external call is not issued unless both the request budget and durable invocation reservation succeed.

If durable invocation reservation fails after request-budget reservation, the in-process request reservation is released and the external call is not issued.

## Completed replay

A completed invocation persists:

- typed result payload;
- canonical result hash;
- committed usage;
- exact target identity;
- stable invocation identity.

After Core restart, an exact call receives `REPLAY` and returns the prior typed result. It does not:

- call the provider or tool again;
- reserve a new request budget;
- add model/tool calls;
- add token or cost usage;
- change result identity.

The gateway validates the stored result against the incoming invocation, selected provider/model or tool/connector, and committed usage before returning it.

## Crash and uncertainty recovery

At store startup:

```text
pending → unknown
reserved read/proposal → unknown
reserved mutation → unknown_side_effect
```

There is no automatic retry.

### Pending recovery

`pending` means durable identity was claimed but no durable external-call reservation exists. Recovery records uncertainty but does not claim model/tool usage.

### Reserved recovery

`reserved` means worst-case usage was durably recorded before the external call boundary. After restart:

```text
committed_usage = previous committed_usage + reserved_usage
reserved_usage  = zero
```

This is conservative because the external system may already have accepted the call.

### Mutation uncertainty

Any uncertain invocation with `effect=mutation` becomes `unknown_side_effect`. It must never be automatically repeated. A domain-specific verifier or explicit operator recovery flow is required before any later action.

## Request-budget alignment

The invocation store is the detailed authority for each external call. The task store is the parent aggregate.

At Core startup:

1. interrupted invocations are recovered;
2. committed invocation usage is summed by `request_id`;
3. the retained parent task budget is raised component-wise to at least that aggregate;
4. existing task usage is never decreased;
5. already-accounted usage is not added twice;
6. over-limit recovered usage marks the task budget exhausted.

This closes the crash case where an invocation contains cost truth but its parent task still shows zero usage.

If the parent task record has already been pruned, the invocation remains authoritative, but no deleted task payload is recreated automatically.

## Model gateway behavior

A governed model invocation persists:

```text
provider_id
model_id
model call count
conservative or actual input/output tokens
estimated micro-USD cost
typed BudgetedModelResult
```

The gateway:

1. selects the cheapest policy-sufficient model;
2. claims durable invocation identity;
3. reserves request budget;
4. persists the same worst-case invocation usage;
5. calls the provider;
6. reconciles actual or conservative usage;
7. validates provider/model identity and output limit;
8. persists one completed or terminal invocation;
9. replays completed output without a second call.

Provider exception text is not persisted. Only a bounded failure code and exception class name are recorded. Prompt, instructions and provider error message are absent from the invocation record and trace.

Python `CancelledError` is propagated after the reserved invocation is marked `unknown` and conservative usage is committed.

## Tool gateway behavior

A governed structured read-tool invocation persists:

```text
tool_id
connector_id
tool call count
typed ToolCallResult
```

Before durable claim, the gateway enforces:

```text
task allowed_data_sources
specialist connector allowlist
specialist tool allowlist
active specialist version
side-effect policy
```

Mutation tools remain blocked in this control-plane increment. They do not reach invocation claim or an executor.

Tool exception text and raw arguments are not persisted or traced. Only the exception class and bounded typed metadata are retained.

## Failure accounting

### Budget rejected before call

```text
invocation state = failed
committed usage = zero
provider/tool call = zero
```

### Provider or tool transport failure after reservation

```text
invocation state = failed
committed usage = conservative reserved usage
provider/tool call may have been accepted
same invocation cannot run again
```

### Coroutine cancellation after reservation

```text
invocation state = unknown
committed usage = conservative reserved usage
CancelledError propagates
```

### Actual usage exceeds budget

The request budget records truthful actual usage and becomes exhausted. The invocation persists that same actual usage in a terminal failed state.

### Result persistence fails after external completion

The gateway returns a storage failure rather than claiming durable success. The on-disk invocation normally remains `reserved`; on the next clean startup it becomes `unknown` with conservative usage. The external call is not automatically repeated.

## Result payload policy

Completed result payloads are:

- typed before storage;
- canonicalized and hashed;
- limited to 1,000,000 bytes;
- immutable after completion.

The store is integrity-checked but not application-level encrypted. A typed result may contain generated model text or a structured tool projection. Gateway and future specialist implementations must persist only the approved result contract, not raw emails, notifications, documents, browser pages, Accessibility trees, credentials or arbitrary connector responses.

Validation errors are wrapped in generic `InvocationStateError` messages so private payload content is not echoed through Pydantic error representations.

## Direct model endpoint

The legacy direct endpoint:

```text
POST /v1/model/text
```

previously bypassed task budgets and invocation durability. It is now operator-authenticated and returns HTTP 410:

```text
ungoverned_model_endpoint_disabled
```

It remains disabled until an explicit model catalog, pricing policy, task budget and durable invocation identity are supplied through a governed runtime.

## Cancellation and expiry

Before durable reservation:

```text
cancel → cancelled
expire → expired
usage  → zero
```

After durable reservation, cancellation or expiry cannot prove the external call did not occur. The invocation therefore becomes `unknown` or `unknown_side_effect` with conservative committed usage.

Full task-to-child-invocation cancellation enumeration and adapter cancellation are Phase 1 Step 1.6. This store provides the required terminal semantics but does not yet expose the complete orchestration propagation layer.

## Retry policy

Automatic retry is disabled.

The schema contains `parent_invocation_id` and `attempt` so a future explicit retry can form an auditable chain. PR #39 does not expose a retry API and does not mint retry identities automatically.

A future retry must:

- use a new invocation ID;
- link to a terminal prior invocation;
- reserve retry and call budgets explicitly;
- be prohibited for unresolved mutation effects;
- preserve the prior terminal record unchanged.

## Retention and backup

PR #39 does not prune invocation records. This avoids silently losing replay and uncertainty evidence but means the database can grow.

Until bounded tombstone/artifact retention is designed:

- monitor database and WAL size;
- use SQLite-aware online backup or a clean shutdown copy;
- preserve the database plus WAL/SHM during incident capture;
- do not manually edit production rows;
- never reset the store to resolve an uncertain side effect.

## Diagnostics

Useful incident fields:

```text
Core commit SHA
store path and schema version
SQLite integrity result
counts by state/kind/effect
oldest pending/reserved/unknown invocation
provider/model/tool/connector identity
reserved and committed usage
parent request and invocation IDs
result hash and payload size
```

Do not publish task text, model output, tool arguments or result payload content in diagnostic logs.

## Current limitations

- no specialist execution runtime yet;
- no automatic retry or explicit retry API;
- task-to-invocation cancellation propagation is not complete until Step 1.6;
- no domain-specific verifier for `unknown_side_effect` exists here;
- invocation result payloads are not application-level encrypted;
- no terminal retention or compact tombstone policy exists;
- one invocation-store path supports one active Core process;
- traces remain process-local;
- no live provider is used in ordinary CI;
- no physical Galaxy A53 claim is related to this Core-only store.
