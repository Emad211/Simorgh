# ADR 0014: Crash-safe durable agent-task identity and routing recovery

- Status: Accepted
- Date: 2026-07-25
- Governing directive: `docs/SIMORGH_MASTER_DIRECTIVE.md`
- Implementation issue: #36
- Implementation PR: #37

## Context

The first specialist-agent increment routed a typed `TaskEnvelope` to one primary specialist and enforced deterministic Persian routing, budgets and process-local idempotency. Its task records lived only in memory.

That was sufficient to prove routing contracts, but it was not sufficient for a permanent personal colleague:

- restarting Core lost task status and cancellation;
- an exact retry after restart could create a new routing decision;
- a crash during a provider-backed classifier could leave external cost uncertain;
- later Voice, Scheduled Mission, Channel, Skill and Work Graph runtimes would have no durable task authority;
- a routing API could not honestly distinguish never-started work from work interrupted after a durable claim.

Android action durability already uses a separate domain-specific journal. Agent tasks have different identities, phases and retention semantics and must not be mixed into the Android action journal.

## Decision

Simorgh Core will maintain a native versioned `AgentTaskStore` independent from Android action storage.

The production implementation is SQLite with:

```text
journal_mode = WAL
synchronous = FULL
foreign_keys = ON
busy_timeout = 5000 ms
```

One active Core process owns one task-store path. Multi-process leader election and a distributed lease are not part of this increment.

Each row stores:

- stable `request_id`;
- immutable canonical task fingerprint;
- current typed phase;
- terminal marker;
- immutable creation time;
- non-decreasing update time;
- canonical JSON of a versioned `AgentTaskStoreEntryV1`;
- SHA-256 of that canonical payload.

Indexed columns are checked against the decoded payload on every load. SQLite integrity checks and Pydantic contract validation are both required.

### Write-ahead task claim

A new task is persisted in phase `routing` before `SpecialistRouter.route()` is called.

```text
validate TaskEnvelope
    ↓
calculate immutable task fingerprint
    ↓
persist routing claim
    ↓
invoke deterministic/model-assisted router
    ↓
persist typed routing decision
```

If the initial claim cannot be stored, the Router is never invoked.

### Exact replay

A repeated submission with the same `request_id` and identical canonical task content returns the existing durable record.

It does not invoke the Router, classifier, model or tool again.

The same request ID with different task content is a conflict.

This replay guarantee applies while the terminal record remains inside configured retention. A compact long-lived request tombstone is deferred; terminal pruning must not be described as indefinite replay protection.

### Interrupted routing

A persisted `routing` phase found during Core startup means the previous process ended after claiming the task but before durably recording a routing result.

Simorgh converts it to:

```text
unknown
```

and records that automatic replay is blocked.

The task is not automatically routed again because a classifier or future external routing dependency may already have accepted work or incurred cost.

`unknown` is an honest terminal recovery state. A later explicit operator recovery workflow may inspect it, but this ADR does not authorize retry.

### Budget recovery

Budget reservation identities are process-local. When a durable budget snapshot already contains unresolved reserved usage, recovery converts that usage conservatively to committed usage.

This means:

- persisted uncertain usage is not treated as free;
- the reservation is not recreated;
- the recovered task cannot silently regain that budget;
- over-limit recovery truthfully marks the budget exhausted.

Persisted elapsed time becomes an offset for the new process's monotonic timer.

This task-store increment persists admission and terminal routing snapshots. It does not journal every intermediate model/tool reservation while an external call is in flight. Therefore a crash during such a call yields `unknown`, but exact provider-cost recovery requires the durable invocation store in Phase 1 Step 1.2.

### Cancellation and expiry

Cancellation and expiry are durable task phases.

- cancellation is idempotent;
- cancellation cannot be reversed;
- the first cancellation reason is immutable;
- a cancelled record requires a cancelled budget snapshot;
- a restored cancelled budget rejects all future reservations;
- an already-expired task is stored without entering Router/model/tool paths.

Python coroutine cancellation is not silently converted into an ordinary routing error. The task is durably marked `unknown`, then `CancelledError` continues to propagate.

### State transitions

The current routing-only runtime permits:

```text
routing → any typed routing terminal, cancelled, expired or unknown
routed/clarification/escalation/budget/policy/contract terminal → same or cancelled
unknown → unknown or cancelled
cancelled → cancelled
expired → expired
```

Task content, fingerprint, creation time, routing decision, first cancellation reason and budget limits are immutable.

Committed usage and elapsed time cannot decrease. Wall-clock rollback cannot reverse durable task chronology.

Later specialist-execution phases require a new schema/ADR rather than overloading these transitions silently.

### Retention

Only terminal records are pruned. Nonterminal `routing` claims are never removed by terminal retention.

Terminal retention is bounded by configuration and removes the oldest terminal records first. The store is operational state, not an indefinite audit archive.

### Startup and shutdown

Core startup:

1. opens the Android action journal;
2. opens the agent-task store;
3. verifies schema/integrity;
4. configures both control planes;
5. recovers interrupted routing to `unknown`;
6. begins serving requests.

Core shutdown detaches the durable task store only after active request handling has ended, then closes SQLite.

### Error semantics

- unsupported schema: startup fails closed;
- database or payload corruption: startup/read fails closed;
- immutable new-task identity conflict: HTTP 409 at the task API;
- unavailable durable store: HTTP 503;
- unexpected failure after durable routing claim: task becomes `unknown`, API returns typed 503;
- a durable transition conflict is treated as an unhealthy store/control-plane condition, not as a user conflict;
- the first durable operation failure latches the control plane unhealthy;
- after the latch, submit/status/cancel cannot serve stale in-memory state;
- successful explicit store reconfiguration or process restart is required to clear the latch;
- there is no fallback to volatile execution after a durable-store failure.

## Consequences

### Positive

- task identity and status survive restart;
- exact replay inside retention does not duplicate routing/model cost;
- cancellation and expiry survive restart;
- interrupted work is reported honestly;
- future Voice, Scheduling, Channels and Work Graph have a native durable task edge;
- corrupt or changed state cannot be silently accepted;
- stale in-memory records are unavailable after a durable write failure;
- Android and agent-task durability remain domain-isolated;
- ordinary CI can exercise all behavior without a live provider.

### Negative

- task submission now depends on local durable storage;
- startup can fail because of schema or integrity problems;
- `unknown` tasks require explicit future recovery tooling;
- SQLite writes add latency before routing;
- terminal retention bounds replay protection unless a later tombstone is retained;
- one store path supports one active Core process only;
- task text is stored as part of `TaskEnvelope` and requires caller-side data minimization;
- the database is integrity-checked but not application-level encrypted;
- exact in-flight provider cost and invocation recovery remain separate follow-up work;
- process-local traces are not yet a durable audit log.

## Rejected alternatives

### Keep task state in memory

Rejected because it cannot support crash-safe daily operation or exact replay.

### Re-route every pending task after restart

Rejected because prior classifier/provider acceptance and cost may be uncertain.

### Store agent tasks in the Android action journal

Rejected because identities, phases, recovery and retention differ, and coupling would open multiple trust boundaries in one store.

### Persist only a task fingerprint

Rejected because cancellation, budget, routing result and operator status would remain unavailable.

### Treat persisted unresolved reservations as released after restart

Rejected because an external system may already have accepted the call.

### Fall back to in-memory mode when SQLite fails

Rejected because it would silently discard the promised durability boundary.

### Continue serving old in-memory records after a write failure

Rejected because the memory record and durable authority may disagree.

### Resume model/tool execution from serialized Python stack state

Rejected because provider/tool side effects and library/runtime state cannot be reconstructed safely from local stack serialization.

## Validation

Automated tests cover:

- SQLite round trip and reopen;
- exact replay across separate Core lifespans;
- same ID/different content conflict;
- durable cancellation;
- interrupted routing recovery to `unknown` without Router invocation;
- coroutine cancellation propagation;
- durable-operation failure latching;
- stale in-memory read/replay rejection after storage failure;
- unsupported schema;
- payload hash corruption;
- indexed-column tampering;
- invalid phase transition;
- terminal pruning without removing routing claims;
- conservative restoration of persisted reservations;
- elapsed-time restoration;
- restored cancellation and budget exhaustion;
- wall-clock rollback without reversing durable chronology;
- byte-exact reconstruction of the governing source directive;
- full Core and Android CI with fake/local dependencies only.

Exact accepted Head and CI evidence are recorded in PR #37 and the merge commit rather than hard-coded here, so documentation edits cannot make the ADR's validation SHA stale.

## Follow-up

Phase 1 continues with:

1. durable invocation store;
2. specialist execution interface;
3. typed result/artifact contracts;
4. governed read-only tools;
5. cancellation propagation;
6. context compiler;
7. end-to-end trace;
8. one complete durable GitHub read workflow.
