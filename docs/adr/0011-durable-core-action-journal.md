# ADR 0011: Durable Core Android action journal

- Status: Accepted
- Date: 2026-07-25

## Context

Android already commits every accepted command to an encrypted write-ahead ledger and retransmits one stable result envelope until Core acknowledges it.

Core originally stored `DeviceActionRecord` objects only in process memory. A restart at the wrong boundary could therefore create this liveness failure:

```text
Android executes or completes action
        ↓
Core restarts before durable result acknowledgement
        ↓
Android reconnects and retransmits exact result
        ↓
new Core process has no action record
        ↓
Core returns unknown_action
        ↓
Android correctly keeps its result ledger locked
        ↓
all later Android actions remain blocked
```

A durable Core journal is required without weakening Android's at-most-once bias or blindly redispatching uncertain side effects.

## Decision

Core will persist every owned Android action in a versioned SQLite journal before the corresponding state transition becomes externally visible.

### Storage engine

The first implementation uses Python's standard-library SQLite driver with:

```text
journal_mode = WAL
synchronous = FULL
foreign_keys = ON
busy_timeout = 5000 ms
BEGIN IMMEDIATE write transactions
```

SQLite is selected because Simorgh currently has one private Core process, requires local transactional durability, and does not need an external database service for the first personal deployment.

### Schema version

The database contains a metadata table with explicit schema version `1` from the first release.

An unknown version fails startup. Core never guesses a migration or opens newer state as older state.

Future migrations must:

1. run inside an explicit transaction;
2. validate all converted rows;
3. update the metadata version only after successful conversion;
4. preserve or reject stable action/result identities deterministically;
5. include rollback and mixed-version tests.

### Durable record

Each journal entry stores at minimum:

- journal schema version;
- device ID;
- complete typed command;
- exact command envelope and message ID;
- SHA-256 of canonical command payload;
- action phase and timestamps;
- delivery count and latest delivery Session ID;
- command acknowledgement;
- stable cancellation envelope and acknowledgement;
- complete typed result;
- result envelope message ID;
- result correlation ID;
- SHA-256 of canonical result payload;
- last result ACK status and send timestamp;
- bounded diagnostic detail.

Indexed SQLite columns duplicate critical lookup fields:

- device/action ID;
- device/command ID;
- command message ID;
- result message ID;
- phase;
- terminal flag;
- timestamps.

On load, those indexed values must exactly match the canonical payload. A mismatch is corruption, not a repair opportunity.

### Canonical integrity

Complete entries are serialized as sorted, whitespace-free UTF-8 JSON and protected by SHA-256.

The entry itself also contains command and result payload hashes. This produces three distinct checks:

1. SQLite page integrity through `PRAGMA quick_check`;
2. complete journal-entry hash;
3. command/result cross-field and payload-hash validation.

Hash comparison uses constant-time comparison.

This is integrity detection, not encryption. The Core host and journal path remain inside the user's trusted private environment. Secret provider keys are never part of action records.

### Identity constraints

The journal enforces:

- primary key `(device_id, action_id)`;
- unique `(device_id, command_id)`;
- globally unique command-envelope message ID;
- globally unique non-null result-envelope message ID.

Reusing a stable identifier for different durable content fails atomically and preserves the original row.

### Write-before-visible-transition

Every broker transition follows:

```text
construct complete candidate record
        ↓
validate candidate
        ↓
commit candidate to journal
        ↓
replace in-memory record
        ↓
perform or acknowledge external effect
```

Examples:

- persist `queued` before the operator receives `202`;
- persist delivery ownership before or immediately around network send according to the delivery protocol;
- persist command ACK before status API exposes `accepted`;
- persist result and stable result-envelope identity before sending `device.action_result_ack`;
- persist ACK-sent bookkeeping after the ACK write succeeds;
- persist cancellation ownership before sending the cancellation envelope;
- persist terminal expiry before exposing it.

A journal write failure does not partially publish an in-memory transition. The broker enters a fail-closed unhealthy state until reconfigured or restarted.

### Startup recovery

On Core startup:

1. open and integrity-check the journal;
2. load and validate every retained row;
3. rebuild action and command ownership indexes;
4. reject duplicate or contradictory ownership;
5. mark loaded non-terminal records as recovered runtime state;
6. expire records whose original command deadline elapsed;
7. expose terminal history and active ownership to APIs.

Corruption fails application startup. Core does not start an action gateway with a partially trusted subset.

### Command redelivery after restart

Recovery distinguishes whether the command might have crossed the Android boundary.

#### Never delivered

A recovered `queued` record with:

```text
delivery_count = 0
last_session_id = null
command_ack = null
```

may be delivered to a current compatible Session while its original deadline remains valid.

#### Delivery may have occurred

A recovered record with delivery count greater than zero, a delivery Session, or a command ACK is **not** redispatched merely because Core restarted.

Core waits for:

- Android's exact persisted result replay;
- a valid cancellation/result message where applicable;
- or the original command deadline.

This preserves the at-most-once bias. Restart is never interpreted as proof that Android did not receive or execute the command.

### Result recovery

When Core receives `device.action_result`:

1. validate action, command, correlation, and semantic evidence;
2. construct the stable durable result identity from the incoming envelope;
3. persist result payload, hash, envelope ID, correlation ID, and terminal phase;
4. send `device.action_result_ack`;
5. after successful socket write, persist ACK status and send timestamp.

If Core crashes after step 3 and before step 4, Android retransmits the exact result. The restarted broker finds the durable result:

- identical result envelope ID, correlation, and payload → `duplicate` ACK;
- different payload or identity under the same action → conflict/rejected ACK;
- truly unknown action → `unknown_action`.

No Android side effect is repeated.

### Observation evidence boundary

Successful `open_app` results are semantically verified against Core-acknowledged observation evidence.

This journal increment guarantees recovery when Core already persisted the validated result before restart. It does not by itself make the full observation registry durable.

If Core restarts before ever validating an incoming success result, old before/after observation references may no longer exist in process-local observation history. Such a result remains unverified and must fail closed until compact observation evidence is also made durable or replayed.

This limitation must be documented and must not be described as full arbitrary-result recovery.

### Result ACK bookkeeping

The journal stores the last ACK status and successful send timestamp. This is operational evidence, not proof that Android received the ACK.

Android remains the source of truth for whether its encrypted result ledger was cleared:

- if ACK delivery was lost, Android retransmits;
- Core sends `duplicate` for identical durable result;
- ACK bookkeeping is updated after each successful Core socket write.

### Retention

All non-terminal records are retained.

Terminal records use bounded retention, initially 256 entries across the journal. Pruning occurs in the same transaction as a terminal upsert and removes the oldest terminal rows only.

Retention never deletes an active action or changes single-flight ownership.

### Corruption behavior

The following fail closed:

- SQLite integrity check not equal to `ok`;
- unreadable JSON;
- complete entry hash mismatch;
- indexed-column/payload mismatch;
- invalid Pydantic schema;
- command/result/cancellation identity mismatch;
- unknown journal schema version;
- duplicate durable command/action/envelope ownership.

Core does not silently delete, repair, or skip a corrupt active row. Recovery requires explicit operator intervention and preserved forensic files.

### Configuration

Core receives a configurable journal path:

```text
SIMORGH_ACTION_JOURNAL_PATH
```

Production/private deployments use a persistent filesystem path. Tests use one isolated temporary path per test application lifespan.

The journal is opened during FastAPI startup and closed during shutdown. Startup failure prevents the service from reporting healthy.

## Consequences

### Positive

- Core restart no longer forgets owned Android actions;
- exact persisted Android results can be acknowledged after restart;
- duplicate and conflicting result replay become deterministic;
- active-action single flight survives restart;
- operator status history survives process death;
- command identity and result identity remain stable;
- corruption is detected before action execution resumes;
- no external database service is required for the private first deployment;
- Android's at-most-once bias remains intact.

### Negative

- SQLite writes add latency before action state transitions;
- Core requires a writable durable filesystem;
- WAL and database files must be backed up together through SQLite-aware methods;
- process-local observation evidence still limits recovery of a success result never validated before restart;
- terminal retention is bounded and old historical actions are eventually pruned;
- a corrupt row prevents action-gateway startup rather than allowing partial service;
- multi-Core active/active deployment is outside this design.

## Rejected alternatives

### Keep only Android's encrypted ledger

Rejected because a restarted Core cannot associate a retransmitted result with the original command or safely acknowledge it.

### Persist only terminal results

Rejected because active ownership, command identity, delivery uncertainty, cancellation, and single-flight state must survive restart.

### Redispatch every non-terminal command after restart

Rejected because delivery or execution may already have occurred.

### Store ad hoc JSON files per action

Rejected because atomic multi-index uniqueness, bounded pruning, integrity queries, and migration are more reliable in SQLite transactions.

### Use SQLite with default durability settings

Rejected because action/result acknowledgement boundaries require explicit WAL and `synchronous=FULL` behavior.

### Skip corrupt rows and load the rest

Rejected because a skipped active row can allow a duplicate side effect or violate device single flight.

### Treat ACK-sent timestamp as proof of Android receipt

Rejected because the socket may close after Core writes and before Android processes the message. Exact result replay remains required.

## Validation

Storage tests cover:

- close/reopen round trip;
- in-memory/SQLite validation parity;
- complete payload tampering;
- indexed-column tampering;
- unknown schema version;
- command/action/message identity conflict;
- transaction atomicity;
- terminal retention;
- durable deletion;
- closed-journal behavior;
- result payload hash and ACK-shape validation.

Integration tests must additionally cover:

- write-before-status visibility for every phase;
- recovered active single-flight ownership;
- safe delivery of never-delivered queued command;
- no redispatch of possibly delivered or accepted command;
- Core restart after result persistence but before ACK;
- exact Android result replay acknowledged as duplicate;
- conflicting result replay rejected;
- next action accepted after Android clears its ledger;
- cancellation and expiry recovery;
- startup failure on corruption;
- isolated journal paths across tests.
