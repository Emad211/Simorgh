# ADR 0021: Durable correlated trace is a source-linked audit projection

- Status: Accepted
- Date: 2026-07-29
- Phase: 1.8
- Issue: #59
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
12. If retained authority advances after an immutable request terminal, typed supersession and resolution events preserve historical status while establishing current status.
13. Direct producer projection occurs only after the owning durable transition commits; projection failure never triggers execution retry.
14. Model/tool child correlation requires exact retained identity: classifier invocation ID or one unambiguous shared cancellation owner.
15. Online backup is the reviewed live-copy mechanism for the WAL database; restore must pass integrity and causal load validation.

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
- historical gaps remain visible even when typed resolution marks them resolved for current status;
- producer wrappers and current-status reconstruction add explicit implementation complexity.

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

Phase 1.9 adds explicitly budgeted live-provider staging. Phase 1.10 adds the complete GitHub workflow and presentation boundary. Public trace UI/export, archival tombstones and vendor telemetry remain separate reviewed decisions.
