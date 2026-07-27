# ADR 0019: Durable task-to-invocation cancellation propagation

- Status: Accepted by Phase 1.6 implementation; merge evidence pending PR #54 final gate
- Date: 2026-07-27

## Context

Simorgh already had durable task cancellation, durable model/tool/specialist invocation identity, conservative restart uncertainty, process-local specialist cancellation tokens and governed GitHub reads. It did not yet have one native mechanism that propagated an accepted task cancellation to all owned invocations, blocked later admission, coordinated optional adapter cancellation and preserved usage honestly.

Cancellation crosses an uncertainty boundary. A request to cancel a model, tool or mutation cannot by itself prove that the remote system did not start or complete the work. Treating cancellation acceptance as proof of non-execution could erase cost, hide a side effect and permit an unsafe retry.

Task and invocation records are separate native authorities. The design therefore needs a race-safe relationship without merging them into one store or creating a second task authority.

## Decision

The durable `AgentTaskStore` remains the source of truth for task cancellation. After the cancellation request is persisted, the `InvocationStore` accepts a derived immutable `InvocationCancellationFence` keyed by task `request_id`.

The fence contains a deterministic snapshot of every invocation owned by the task and its canonical SHA-256. Invocation `begin` and `reserve` check the fence under the store lock/transaction. Work admitted before the fence is included in the snapshot and settled; work arriving after the fence is rejected.

Cancellation uses this order:

```text
persist task cancellation request
  → cancel task budget
  → accept invocation fence and ownership snapshot
  → signal process-local owners
  → settle pending work cancelled
  → invoke optional typed adapter cancellation
  → settle reserved work using proof or conservative uncertainty
  → persist immutable cancellation result
  → emit bounded audit metadata
```

Pending invocations become `cancelled` with zero usage. A reserved read/proposal becomes `cancelled` only when a typed adapter acknowledgement proves external execution was not entered and confirms reservation release. Otherwise it becomes `unknown` and its reservation is conservatively committed. A reserved mutation always becomes `unknown_side_effect`; cancellation does not authorize compensation or prove non-execution.

Completed and other terminal invocations remain immutable.

A process-local `CancellationOwnerRegistry` signals cooperative owners at most once and blocks late registration after a durable fence. A separate `InvocationCancellationAdapterRegistry` exposes the optional typed cancellation capability. Both registries are subordinate to durable state and are empty after restart.

Cancellation requests/results, ownership projections, adapter acknowledgements and per-invocation outcomes are strict versioned contracts. Exact replay is idempotent; changed content under the same identity conflicts.

## Consequences

- Cancellation cannot erase committed cost or an authoritative completed result.
- Reserved uncertainty is visible as `unknown` or `unknown_side_effect` rather than overstated success.
- Future invocation admission and usage reservation fail closed after the durable fence.
- A narrow proof-of-non-entry path can safely release a reserved read/proposal without widening mutation authority.
- Task and invocation stores remain separate, with invocation ownership derived only from durable invocation records.
- Parent/child invocation ownership is explicit, same-task and attempt-ordered.
- Process-local signals and adapter handles improve responsiveness but never replace durable truth.
- Adapter exceptions and raw acknowledgements do not enter durable failure metadata or traces.
- The adapter-cancellation disable switch can remove the risky external hook while preserving durable cancellation and conservative settlement.
- Ordinary CI remains zero-network and zero-cost by using fake adapters.

## Rejected alternatives

- Mark every reserved invocation `cancelled` when the operator asks to cancel.
- Release all reserved usage after an adapter returns `accepted`.
- Retry a cancelled or uncertain invocation automatically.
- Reconstruct stale process-local cancellation tokens after restart.
- Let providers/connectors select ownership or cancellation authority.
- Store provider handles, credentials or raw cancellation responses in Core contracts.
- Merge task and invocation stores solely to implement cancellation.
- Add compensation, GitHub mutation, Voice, MCP or a distributed cancellation coordinator in this trust-boundary PR.

## Operational rules

- No adapter hook runs before durable task cancellation acceptance.
- A late owner/adapter registration is rejected after the fence.
- Duplicate cancellation cannot double-signal, double-release or double-commit.
- A disabled adapter registry preserves admission fencing and conservative uncertainty.
- Store corruption or schema mismatch fails closed; process-local state must not be used to infer durable cancellation.
- Audit events contain identifiers, states, counts and hashes only; task/provider/connector content and operator reason text are excluded.

## Follow-up

Phase 1.7 adds bounded context compilation, Phase 1.8 completes correlated non-secret tracing, Phase 1.9 adds explicitly budgeted live-provider staging and Phase 1.10 composes the complete Persian GitHub read workflow. Voice, Notification, MCP, Memory and Work Graph remain parked until the required Phase 1 sequence is complete.
