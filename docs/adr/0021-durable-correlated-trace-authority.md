# ADR 0021: Durable correlated trace is a source-linked audit projection

- Status: Proposed
- Date: 2026-07-29
- Phase: 1.8
- Issue: #57
- Pull request: #60

## Context

Simorgh already has independent durable authorities for tasks, invocations, contexts, results and Android actions. Existing process-local trace events are useful for tests and immediate diagnostics but do not survive restart, do not provide stable per-request sequencing and cannot reconstruct one route-to-result history.

Persisting arbitrary trace metadata would create a second, weaker source of truth and a privacy risk. Replaying event producers after restart could also misrepresent replay as new work or duplicate usage.

## Decision

Introduce an independent durable trace authority with these rules:

1. Trace is a projection, never execution authority.
2. Every persisted event is strict, typed and linked to one retained source-authority ID and SHA-256.
3. Trace and event IDs are deterministic; timestamps are excluded from canonical identity.
4. Sequence is assigned transactionally per trace.
5. Exact duplicates replay idempotently; changed content conflicts.
6. Result events carry no new usage; invocation terminal events are the single trace location for committed invocation usage.
7. Missing retained authority becomes an immutable typed gap. Reconciliation cannot erase it or synthesize success.
8. Startup reconciliation uses local stores only and makes zero external calls.
9. SQLite trace storage has its own path, lock, schema, health latch, backup boundary and retention policy.
10. Retention deletes only whole terminal traces, protects every nonterminal task and invocation authority, and rechecks those authorities immediately before deletion.
11. Store registry replacement is fail-closed: candidate load/validation occurs before replacing the current store.
12. If retained authority advances after an immutable request terminal, startup reconciliation records a typed source-mismatch gap; it does not rewrite the old terminal or fail startup.

## Causal model

The initial accepted path is:

```text
task -> routing -> context -> specialist invocation -> result -> request terminal
```

Retries form a parent-invocation chain. A retry's parent event is the terminal event of the prior invocation; its causation event is its own context bundle. A request receives one terminal event after the final authoritative outcome, not one terminal event per attempt.

## Consequences

### Positive

- exact audit reconstruction after restart;
- no private body text in trace storage;
- deterministic idempotent reconciliation;
- explicit gaps and uncertainty;
- no duplicate usage attribution on result commit;
- bounded terminal history;
- independent corruption and process-ownership boundary.

### Costs

- another SQLite database and operational backup target;
- source stores must remain available long enough for reconciliation;
- typed event families require reviewed schema evolution;
- historical gaps remain visible even if later source data appears; a future typed resolution/supersession event is required for live post-terminal retry and cancellation transitions.

## Rejected alternatives

### Persist existing generic `TraceEvent.metadata`

Rejected because arbitrary keys and values are too weak for durable authority and increase privacy/secret risk.

### Store traces inside task or invocation databases

Rejected because trace sequencing, retention, reconstruction and corruption semantics differ from each source authority.

### Regenerate a natural-language timeline after restart

Rejected because model generation is nondeterministic, costs money and could invent or expose private content.

### Prune by age alone

Rejected because age does not prove that a task or invocation is terminal.

### Count usage on both invocation and result events

Rejected because a trace sum would double-count one execution.

## Follow-up

The next Phase 1.8 increments wire direct typed producers, complete model/tool/cancellation correlation, add full acceptance and operational evidence, and move this ADR to Accepted only with exact-head Core and Android CI plus review audit.
