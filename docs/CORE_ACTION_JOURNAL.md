# Durable Core action journal

Status: implemented for private single-process Simorgh Core deployments.

## Purpose

The Android app already stores accepted commands and unacknowledged results in an encrypted device-side write-ahead ledger. Core also needs durable ownership state; otherwise a Core restart can forget the original action and answer an exact Android result replay with `unknown_action`.

The Core journal persists:

- action and command identity;
- exact command envelope identity;
- phase and delivery uncertainty;
- command acknowledgement;
- cancellation envelope and acknowledgement;
- exact result envelope identity and payload hash;
- result ACK send bookkeeping;
- bounded terminal history.

The primary safety rule is:

> Core restart is never treated as proof that Android did not receive or execute a command.

## Configuration

```dotenv
SIMORGH_ACTION_JOURNAL_PATH=.simorgh/action-journal.sqlite3
SIMORGH_ACTION_JOURNAL_MAX_TERMINAL_RECORDS=256
```

Requirements:

- the path must be writable by the Core process;
- the filesystem must survive process and host restarts;
- only the private Core account should have access;
- do not place the journal in a temporary container layer unless that layer is mounted persistently;
- preserve enough free space for the database and its SQLite sidecar files.

A relative path is resolved to an absolute path at startup. `~` is expanded.

## SQLite durability mode

Core opens the journal with:

```text
journal_mode = WAL
synchronous = FULL
foreign_keys = ON
busy_timeout = 5000 ms
BEGIN IMMEDIATE write transactions
```

The first schema version is `1`. A newer or unknown schema version prevents Core startup; no best-effort downgrade is attempted.

## Startup sequence

```text
open SQLite
    ↓
validate schema version
    ↓
PRAGMA quick_check
    ↓
verify row SHA-256
    ↓
validate typed payload and indexed-column equality
    ↓
rebuild action and command ownership
    ↓
expire elapsed records durably
    ↓
start device and operator APIs
```

Any corruption or contradictory active ownership fails startup. Core does not skip an unsafe row and continue with a partial view.

## Write-before-visible state transitions

For each action mutation:

```text
construct complete candidate
    ↓
validate phase and immutable identity
    ↓
commit one SQLite transaction
    ↓
replace in-memory state
    ↓
return API status or perform network write
```

Consequences:

- `queued` exists durably before the operator receives `202`;
- delivery uncertainty is persisted before a command socket write;
- command ACK is persisted before the status API exposes it;
- cancellation ownership is persisted before sending cancellation;
- result identity is persisted before sending `device.action_result_ack`;
- successful ACK-send bookkeeping is persisted after the socket write.

If a runtime journal write fails, action APIs fail closed with HTTP `503` and code:

```text
action_journal_unavailable
```

Restart or explicit operator repair is required. The broker does not keep mutating memory after durable state becomes unreliable.

## Recovery classes

### Never delivered

A recovered action is safe to send when all of these are true:

```text
phase = queued
delivery_count = 0
last_session_id = null
command_ack = null
```

Core reuses the exact original command envelope and only delivers it while the original command deadline remains valid and the current Session advertises the required execution capability.

### Delivery may have occurred

If any of these are true:

```text
delivery_count > 0
last_session_id != null
command_ack != null
```

Core does not redispatch after restart. It transfers result ownership to the current device Session and waits for:

- the exact persisted Android result replay;
- a valid result or cancellation outcome;
- or the original command deadline.

This may sacrifice liveness after an uncertain failed send, but it prevents duplicate side effects.

### Result persisted before ACK

```text
Core validates result
    ↓
persists result envelope ID, correlation, payload and hash
    ↓
Core crashes before ACK
    ↓
Android replays exact result
    ↓
restarted Core returns duplicate ACK
    ↓
Android clears its encrypted ledger
```

A different result envelope ID, correlation, or payload under the same action is a conflict and is not accepted as a duplicate.

## Immutable identity

After an action row exists, these fields cannot be rewritten:

- device/action ownership key;
- complete command;
- command envelope and message ID;
- command payload hash;
- creation time;
- previously stored command acknowledgement;
- previously stored cancellation envelope and acknowledgement;
- previously stored result identity and content.

These counters and timestamps are monotonic:

- `updated_at_ms`;
- `delivery_count`;
- result ACK send time.

Phase transitions are explicitly allowlisted. For example, `accepted → delivered` and `completed → accepted` are rejected.

## Result ACK bookkeeping

Core stores the last successfully written ACK status and timestamp for `accepted` or `duplicate`.

This does **not** prove Android received or processed the ACK. If delivery was lost, Android remains authoritative and retransmits the exact result. Core then sends another duplicate ACK.

## Retention

- every non-terminal record is retained;
- terminal history is bounded by `SIMORGH_ACTION_JOURNAL_MAX_TERMINAL_RECORDS`;
- pruning happens in the same transaction as terminal upsert;
- oldest terminal records are removed first;
- an active action is never pruned.

A value of `0` retains no terminal history after each terminal transaction, but active ownership still remains durable until terminal transition.

## Backup and restore

Because the journal uses WAL mode, do not copy only the main `.sqlite3` file while Core is running.

Preferred methods:

1. stop Core cleanly, then copy the database file; or
2. use SQLite's online backup API/tool against the live database.

Preserve the journal as sensitive operational state. It contains app/package targets, action details, and execution outcomes, though it does not contain AvalAI keys or Android device tokens.

After restoring:

- keep the same complete database state;
- do not merge rows manually;
- run Core once and allow integrity/schema validation to complete;
- investigate startup failure rather than deleting an active row.

## Corruption response

Fail-closed conditions include:

- `PRAGMA quick_check` not returning `ok`;
- unknown schema version;
- row payload hash mismatch;
- invalid JSON or typed model;
- mismatch between indexed columns and canonical payload;
- invalid command/cancellation/result relationship;
- duplicate durable identity;
- multiple non-terminal actions for one device.

Recommended response:

1. stop Core;
2. copy the database, `-wal`, and `-shm` files for diagnosis;
3. preserve Android's encrypted ledger by not clearing app data;
4. inspect the last known action and device state;
5. repair through a reviewed migration or explicit recovery tool;
6. never delete an uncertain active row merely to unblock dispatch.

## Security boundary

SHA-256 detects accidental corruption and unsynchronised/manual edits when hashes are not recomputed. It is not a substitute for filesystem access control or authenticated encryption.

Protect the Core host with:

- private user permissions;
- encrypted disk where appropriate;
- restricted backups;
- no shared writable directory;
- one active Core process for this journal.

Multi-Core active/active access is outside this design.

## Observation evidence limitation

A successful `open_app` result must be verified against Core-acknowledged observation evidence.

The action journal preserves a success result **after Core has validated and persisted it**. It does not yet make the complete observation registry durable. Therefore:

- crash after validated result persistence is recoverable through exact result replay;
- crash before first validation of a success result may leave its old observation references unavailable;
- such a success claim remains rejected until compact observation evidence is made durable or safely replayed.

Failed, blocked, timed-out, and cancelled results that do not claim successful UI postconditions can be associated with a recovered action without reconstructing old UI evidence.

## Validation coverage

Automated tests cover:

- SQLite close/reopen round trip;
- WAL storage configuration and schema version;
- complete-payload and indexed-column tampering;
- immutable action/command/envelope identity;
- monotonic delivery and phase transitions;
- result identity immutability;
- terminal retention and durable deletion;
- startup failure on unsupported/corrupt state;
- write failure before command visibility;
- never-delivered queued recovery;
- no command redispatch after uncertain delivery;
- active single-flight recovery;
- orphaned Android result acceptance after Core restart;
- crash after result persistence but before ACK;
- exact result replay receiving duplicate ACK;
- conflicting replay rejection;
- next action proceeding after terminal recovery.

See ADR 0011 for the architecture decision and rejected alternatives.
