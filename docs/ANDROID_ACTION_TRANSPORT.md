# Android action transport

Status: implemented typed, capability-gated, restart-safe transport with one live verified side effect: `open_app`.

## Purpose

This subsystem transports one validated Android action from Simorgh Core to one private Android device and returns one typed result without silently duplicating an uncertain side effect.

The transport does not interpret natural language and does not choose screen coordinates. Core accepts a schema-versioned `AndroidActionCommand`, applies semantic and capability checks, persists ownership, and sends it only to a current device Session that advertises the operation's enabled execution capability.

Android validates the command again, writes it to an encrypted device ledger, and delegates it to exactly one installed executor.

## Non-negotiable invariants

1. One device has at most one non-terminal action.
2. Schema availability is not execution permission.
3. Every live operation maps to an explicit versioned device capability.
4. Initial dispatch requires a current connected Session advertising that capability.
5. Negotiation failure occurs before command-envelope creation and broker identity ownership.
6. Core persists action ownership before returning status or crossing a side-effect boundary.
7. `command_id`, `action_id`, and protocol `message_id` are UUIDs with distinct roles.
8. Reconnect reuses only the original envelope; Core restart never blindly resends an uncertain command.
9. Android writes an encrypted active ledger entry before invoking an executor.
10. A completed result keeps one stable result `message_id` until Core acknowledges it.
11. Core persists result identity before writing `device.action_result_ack`.
12. A new Android command is blocked while a prior result remains unacknowledged.
13. WebSocket writes are serialized per device Session.
14. Model-provider credentials never cross the Core boundary.

## Credentials and persistence

```dotenv
SIMORGH_DEVICE_TOKEN=<phone-to-core-websocket-token>
SIMORGH_OPERATOR_TOKEN=<trusted-core-action-api-token>
AVALAI_API_KEY=<core-only-model-provider-key>
SIMORGH_ACTION_JOURNAL_PATH=.simorgh/action-journal.sqlite3
SIMORGH_ACTION_JOURNAL_MAX_TERMINAL_RECORDS=256
```

- `SIMORGH_DEVICE_TOKEN` authenticates the Android WebSocket.
- `SIMORGH_OPERATOR_TOKEN` authorizes action, status, cancellation, and observation-refresh APIs.
- `AVALAI_API_KEY` remains on Core and is unrelated to device authentication.
- The action journal contains operational action state, not bearer tokens or model-provider keys.
- Terminal retention is at least one record; the default is 256.

The shared development device token is not the final pairing design. Per-device revocable credentials remain a later increment.

## Operator API

```http
POST /v1/devices/{device_id}/actions
GET  /v1/devices/{device_id}/actions/{action_id}
POST /v1/devices/{device_id}/actions/{action_id}/cancel
Authorization: Bearer <SIMORGH_OPERATOR_TOKEN>
```

`POST /actions` accepts only `AndroidActionCommand`. Raw natural language never crosses the execution boundary.

## Capability negotiation

Android registration contains a versioned capability list. Core enforces the current Session's list rather than inferring support from SDK level or a historical device profile.

Current live mapping:

```text
open_app -> android.open_app.execution.v1
```

Schema operations reserved for later increments remain non-dispatchable until they have an executor and distinct capability.

Dispatch ordering:

```text
schema validation
    ↓
cross-field semantic validation
    ↓
operation → capability mapping
    ↓
current Session and capability check
    ↓
identifier and single-flight checks
    ↓
command envelope construction
    ↓
durable queued record
    ↓
current-Session revalidation
    ↓
durable delivery uncertainty
    ↓
socket write
```

Typed errors distinguish:

- HTTP 409 `device_not_connected`;
- HTTP 409 `unsupported_device_capability`;
- HTTP 422 `unsupported_operation`;
- HTTP 503 `action_journal_unavailable`.

Initial negotiation failure reserves no identifier. The exact same command can be submitted after a compatible Session registers.

See ADR 0010 and [`CORE_ACTION_JOURNAL.md`](CORE_ACTION_JOURNAL.md).

## Wire messages

| Direction | Type | Correlation rule |
|---|---|---|
| Core → Android | `device.action_command` | stable command-envelope `message_id` |
| Android → Core | `device.action_command_ack` | `correlation_id` = command message ID |
| Android → Core | `device.action_result` | stable result message ID; correlation = command message ID |
| Core → Android | `device.action_result_ack` | correlation = result message ID |
| Core → Android | `device.action_cancel` | stable cancel envelope; correlation = command message ID |
| Android → Core | `device.action_cancel_ack` | correlation = cancel message ID |

Every message remains in protocol envelope `1.0` and is rejected when protocol version, device identity, UUID shape, byte limit, or typed payload is invalid.

## Command acknowledgement statuses

- `accepted`: Android ledger was written and an executor accepted ownership.
- `duplicate`: the exact command is already active or completed.
- `busy`: another action or unacknowledged result owns Android's slot.
- `expired`: deadline elapsed before Android accepted ownership.
- `rejected`: validation, ledger state, or executor availability prevented acceptance.

An ACK proves receipt state only. It does not prove the requested visible state was reached.

## Durable Core action broker

Core stores records in a versioned SQLite journal and mirrors the validated state in memory.

```text
queued → delivered → accepted → completed
                     └────────→ cancelled
queued/delivered/accepted → cancelling → completed/cancelled
queued/delivered/accepted/cancelling → expired
queued/delivered/cancelling → rejected
```

The broker enforces:

- write-before-visible state transitions;
- current-Session capability before new ownership;
- one active action per device;
- unique command and envelope identities;
- immutable command, cancellation, and result identity;
- monotonic delivery count and timestamps;
- allowlisted phase transitions;
- exact command/result correlation;
- rejection of obsolete Session messages;
- bounded durable terminal history;
- duplicate result acceptance only when envelope identity and complete typed payload are identical;
- fail-closed HTTP 503 behavior after runtime journal failure.

SQLite uses WAL, `synchronous=FULL`, `BEGIN IMMEDIATE`, schema versioning, `PRAGMA quick_check`, canonical JSON, SHA-256, indexed-column equality, and strict typed validation.

### Upgrade and downgrade behavior

The newest registered Session is authoritative for new actions.

If a command has never crossed the device boundary and a replacement Session lacks its capability, Core may reject it safely.

If delivery may already have occurred, a downgrade does not prove the side effect never ran. Core:

- does not send the command to the incompatible Session;
- preserves the phase and durable identity;
- waits for a result or original deadline;
- never creates a replacement command implicitly.

### Core restart recovery

A recovered record is redispatchable only when all are true:

```text
phase = queued
delivery_count = 0
last_session_id = null
command_ack = null
```

If delivery count, Session ownership, or command ACK exists, Core transfers result ownership to the new Session but does not resend the command.

This preserves at-most-once behavior even when the previous socket write was uncertain.

## Android encrypted write-ahead ledger

Before executor submission, Android persists:

```text
schema_version
command_envelope_id
command_hash
command
phase = active
```

Properties:

- AES-GCM authenticated encryption;
- non-exportable key from Android Keystore;
- private SharedPreferences ciphertext and IV;
- synchronous commit before executor invocation;
- strict validation on every read.

After completion, Android atomically stores:

```text
phase = completed
result_message_id
result
result_acknowledged = false
```

Reconnect and retry reuse the stable result identity.

## Restart and crash boundaries

### Android process restart during uncertain execution

Android cannot prove the side effect did not start, so it does not replay it. Recovery produces a conservative blocked result:

```text
outcome = blocked
failure_code = internal_error
```

### Core restart after uncertain command delivery

Core does not redispatch. It waits for Android's persisted result or deadline.

### Core crash after result persistence but before ACK

```text
persist exact result
    ↓
Core crashes before ACK
    ↓
Android replays exact envelope
    ↓
Core loads durable result
    ↓
duplicate ACK
    ↓
Android clears ledger
```

A changed result message ID, correlation, or payload is a conflict, not a duplicate.

### Observation evidence limitation

The journal preserves a successful result after Core validated it. The complete observation registry is still process-local. A success claim first arriving after Core restart may lack old before/after evidence and remains rejected until evidence becomes durable or is safely replayed.

Failed, blocked, timed-out, and cancelled results do not claim successful UI postconditions and can be associated with recovered action identity without reconstructing old UI evidence.

## Result publisher and ACK bookkeeping

Android's `ActionResultPublisher` owns one result delivery:

- at most three sends per connection;
- ten-second ACK timeout;
- stable message and correlation IDs;
- failed socket send does not consume an attempt;
- reconnect resumes the persisted result;
- competing results cannot replace active delivery.

Core persists the result before ACK. After a successful ACK socket write, Core journals ACK status and timestamp. That timestamp does not prove Android received the ACK; Android remains authoritative and retransmits if its ledger was not cleared.

For `accepted` or `duplicate`, Android marks the result acknowledged and clears its publisher/ledger state. For `unknown_action` or `rejected`, the encrypted result remains for controlled recovery.

## Cancellation

Cancellation is cooperative, not rollback:

1. Core persists one stable cancel envelope.
2. Android validates command/action identity against its ledger.
3. A matching in-process executor receives `cancel()`.
4. Android replies `accepted`, `duplicate`, `not_found`, or `completed`.
5. The executor still owns the final typed result.

Cancellation may be redelivered after Core restart because it requests stopping work rather than repeating the original side effect.

## Failure matrix

| Failure | Behavior |
|---|---|
| Device disconnected during initial dispatch | HTTP 409; no durable record |
| Capability missing | HTTP 409; no durable record |
| Operation has no executor mapping | HTTP 422; no durable record |
| Journal write fails | HTTP 503; broker stops mutating state |
| Socket write fails after durable delivery attempt | state remains uncertain; exact retry in-process, no blind resend after restart |
| Replacement Session lacks capability before delivery | action may be rejected safely |
| Replacement Session lacks capability after possible delivery | no command redelivery; wait for result/deadline |
| Duplicate active command | Android returns duplicate; executor is not called again |
| Android dies with active ledger | blocked recovery result; command is not replayed |
| Core dies after result persistence | exact replay receives duplicate ACK |
| Result ACK is lost | Android retransmits exact result |
| Result identity/content changes | conflict; durable state is not overwritten |
| Journal schema or integrity is invalid | Core startup fails closed |
| Competing action arrives | HTTP 409; current action retains ownership |

## Automated validation

Core tests cover:

- capability negotiation and absence of command leakage;
- journal close/reopen and schema version;
- payload/index tampering and startup failure;
- immutable command/envelope/result identity;
- monotonic transitions and delivery counts;
- write failure before API/socket visibility;
- safe recovery of never-delivered queued command;
- no redispatch of uncertain delivered/accepted command;
- active single-flight ownership after restart;
- orphaned result acceptance after Core restart;
- crash after result persistence but before ACK;
- exact replay receiving duplicate ACK;
- conflicting replay rejection;
- next action after terminal recovery;
- cancellation, expiry, command ACK, and result correlation.

Android JVM tests cover:

- ledger before handler submission;
- duplicate suppression;
- process-death recovery without replay;
- unacknowledged result blocking the next command;
- stable result retry identity;
- mismatched ACK rejection;
- corrupt ledger fail-closed behavior;
- command/result/cancel protocol round trips.

## Physical Galaxy A53 boundary

Core journal and capability filtering are covered automatically. The `open_app` executor still requires its documented physical Galaxy A53 protocol before One UI validation is claimed.

Record Android/One UI versions, APK commit, advertised capabilities, command/result identities, foreground/background conditions, reconnect/process death, and proof that no uncertain action executes twice.

## Current boundary

Live actions:

```text
open_app(package_name)
open_app(package_name, uri)
```

Other schema operations remain non-dispatchable until they receive an independent executor, versioned capability, deterministic evidence-bound tests, and physical validation where applicable.
