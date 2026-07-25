# Durable agent-task store

Status: implemented for task identity, routing status, cancellation, expiry and crash recovery in PR #37.

This store is the durable authority for the agent-task edge. It is not the Android action journal, invocation store, trace archive, Personal Work Graph or long-term memory.

## Configuration

```text
SIMORGH_AGENT_TASK_STORE_PATH=.simorgh/agent-tasks.sqlite3
SIMORGH_AGENT_TASK_STORE_MAX_TERMINAL_RECORDS=10000
```

The path may be `:memory:` only for isolated tests. Production and daily local use should use a dedicated persistent path.

The configured terminal retention must be positive. Retention affects terminal task records only.

## SQLite guarantees

The production store enables:

```text
PRAGMA foreign_keys = ON
PRAGMA busy_timeout = 5000
PRAGMA journal_mode = WAL       (file-backed databases)
PRAGMA synchronous = FULL
```

The database contains:

```text
agent_task_store_metadata
agent_task_records
```

Every record includes canonical JSON and a SHA-256 integrity hash. Indexed columns such as request ID, fingerprint, phase, terminal marker and timestamps are verified against the decoded payload.

A successful SQLite query alone is not considered sufficient integrity evidence.

## Stored data

One `AgentTaskStoreEntryV1` contains:

```text
schema_version
request_id
task_fingerprint
AgentTaskRecord
```

The `AgentTaskRecord` contains:

```text
TaskEnvelope
phase
creation/update timestamps
RoutingDecision when present
BudgetSnapshot
first cancellation reason when present
bounded operational detail
```

It must not contain:

- AvalAI or other provider credentials;
- operator/device bearer tokens;
- raw trace events;
- model prompts or private model output;
- raw connector payloads;
- raw email, notification, audio or Accessibility content;
- Android action-journal state.

## Task phases

```text
routing
routed
needs_clarification
needs_escalation
budget_exhausted
policy_blocked
contract_invalid
cancelled
expired
unknown
```

In the current routing-only runtime, every phase except `routing` is terminal.

`routed` means a primary specialist was selected. It does not mean specialist work or an external side effect completed.

## Submission sequence

A new task is claimed durably before the Router is called:

```text
validate task
    ↓
canonical fingerprint
    ↓
write phase=routing
    ↓
run SpecialistRouter
    ↓
write typed terminal routing result
```

When the initial durable write fails, no Router, classifier, model or tool invocation occurs.

## Replay

An exact retry with identical task content returns the existing durable record.

```text
same request_id + same canonical task
    → return existing record

same request_id + different canonical task
    → HTTP 409 conflict
```

The existing `decision_id`, creation time, cost and phase remain unchanged.

## Restart recovery

At Core startup, all rows are integrity-checked and loaded.

A row still in `routing` means the prior Core process ended after durable claim and before durable completion. It is converted to:

```text
unknown
```

with detail explaining that automatic replay is blocked.

Submitting the exact task again returns `unknown`; it does not route again.

A future explicit recovery API may inspect and supersede unknown work. It must not silently mutate the existing task identity.

## Budget recovery

`BudgetSnapshot.reserved` is process-local uncertainty. Reservation IDs are not reconstructed after restart.

Recovery converts unresolved reserved usage to committed usage:

```text
recovered committed = previous committed + previous reserved
recovered reserved  = zero
```

This is intentionally conservative. A provider or tool may already have accepted work before the crash.

The previous elapsed time becomes an offset for the new process's monotonic elapsed timer.

A restored cancelled account remains cancelled. A restored over-limit account remains exhausted.

## Cancellation

Cancellation is persisted before it is returned to the caller.

- the first non-empty reason is retained;
- duplicate cancellation returns the same record;
- cancelled budget state survives restart;
- future reservations are rejected;
- cancellation cannot be reversed by task resubmission.

The current step has no long-running specialist execution yet. Later Phase 1 steps will propagate the same cancellation identity into specialist/model/tool invocations.

## Expiry

An absolute deadline already elapsed at submission creates a durable `expired` record.

The task does not enter Router/model/tool paths.

The effective monotonic budget is bounded by the stricter of:

```text
TaskBudget.max_elapsed_ms
absolute deadline remaining at admission
```

## Retention

Only terminal records are pruned.

```text
oldest terminal records → removed first
routing records          → never removed by terminal retention
```

The task store is operational state, not an indefinite audit archive. Long-term task/evidence history belongs to later Work Graph and audit-storage increments.

## Corruption and schema failures

Core fails closed on:

- unsupported schema version;
- failed SQLite integrity check;
- payload hash mismatch;
- invalid JSON or typed contract;
- indexed columns differing from payload;
- immutable identity changes;
- backward timestamps or usage;
- invalid phase transition.

The task API returns no volatile fallback result after a durable-store failure.

### Recovery procedure

1. Stop Simorgh Core.
2. Preserve the database and any `-wal` / `-shm` files as one incident bundle.
3. Record the Core commit SHA and exact error.
4. Do not edit rows manually in the production copy.
5. Work from a copy and run SQLite integrity inspection.
6. Restore from a known-good backup or run a reviewed schema-specific recovery tool.
7. Keep the corrupt copy for diagnosis until recovery is verified.
8. Restart Core and verify task counts, phases and replay behavior.

There is intentionally no `ignore_corruption` setting.

## Backup

Preferred options:

- stop Core and copy the SQLite database after a clean shutdown;
- use SQLite's online backup API from a reviewed backup command;
- back up the database together with WAL state when using filesystem-level live snapshots.

Do not copy only the main database file while Core is actively writing unless the backup mechanism is SQLite/WAL aware.

Secrets are stored elsewhere and are not included in this database.

## Reset for development

With Core stopped, removing the configured agent-task database resets task-routing history. It does not reset:

- Android action state;
- connector credentials;
- provider credentials;
- future invocation/result stores;
- memory or Work Graph state.

Never use a reset as a recovery mechanism for uncertain external side effects.

## Diagnostics

Useful facts to report during an incident:

```text
Core commit SHA
store path
schema version
SQLite integrity result
number of rows by phase
oldest routing/unknown record
terminal retention setting
database/WAL sizes
last startup recovery detail
```

Do not include TaskEnvelope private content in public logs or issue reports.

## Validation

Automated coverage includes:

- round trip and reopen;
- exact replay across separate Core lifespans;
- changed-content conflict;
- cancellation restart persistence;
- routing-to-unknown crash recovery;
- hash and indexed-column tampering;
- unsupported schema;
- transition rules;
- bounded terminal pruning;
- conservative budget restoration.

## Current limitations

- specialist execution is not implemented in this step;
- invocation identities are still process-local until Phase 1 Step 1.2;
- traces are process-local;
- `unknown` has no operator recovery endpoint yet;
- no task-result artifact is stored yet;
- terminal pruning is count-based rather than age/size based;
- no online backup or Doctor command exists yet.
