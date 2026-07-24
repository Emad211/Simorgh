# Android action transport

Status: implemented transport boundary; live side effects remain disabled until an executor is installed

## Purpose

This subsystem transports one validated Android action from Simorgh Core to one private Android device and returns one typed result without silently duplicating an uncertain side effect.

The transport does not interpret natural language and does not choose screen coordinates. Core sends a schema-versioned `AndroidActionCommand`; Android validates it again, records it durably, and delegates it to exactly one installed executor.

## Non-negotiable invariants

1. One device has at most one non-terminal action.
2. `command_id`, `action_id`, and protocol `message_id` are UUIDs with distinct roles.
3. Reconnect redelivers the original command envelope, including the original `message_id`.
4. Android writes an encrypted active ledger entry before invoking an executor.
5. A process restart never blindly repeats an action whose execution state is uncertain.
6. A completed result keeps one stable result `message_id` until Core acknowledges it.
7. A new command is blocked while a prior result is unacknowledged.
8. Action result and observation payloads bypass the generic reconnect queue; their dedicated publishers own retry semantics.
9. Every WebSocket write in Core is serialized per device session.
10. Model-provider credentials never cross the Core boundary.

## Credentials

Two independent bearer credentials are used during development:

```dotenv
SIMORGH_DEVICE_TOKEN=<phone-to-core-websocket-token>
SIMORGH_OPERATOR_TOKEN=<core-action-api-token>
```

- `SIMORGH_DEVICE_TOKEN` authenticates the persistent Android WebSocket.
- `SIMORGH_OPERATOR_TOKEN` authorizes action dispatch, status lookup, and cancellation.
- `AVALAI_API_KEY` remains on Core and is unrelated to device authentication.

The shared development device token is not the final pairing design. A later increment will issue per-device revocable credentials.

## Operator API

```http
POST /v1/devices/{device_id}/actions
GET  /v1/devices/{device_id}/actions/{action_id}
POST /v1/devices/{device_id}/actions/{action_id}/cancel
Authorization: Bearer <SIMORGH_OPERATOR_TOKEN>
```

`POST /actions` accepts only the strict `AndroidActionCommand` contract. Raw natural-language instructions are never accepted by the device executor boundary.

## Wire messages

| Direction | Type | Correlation rule |
|---|---|---|
| Core → Android | `device.action_command` | New stable command envelope `message_id` |
| Android → Core | `device.action_command_ack` | `correlation_id` = command envelope `message_id` |
| Android → Core | `device.action_result` | `correlation_id` = command envelope `message_id`; stable result `message_id` |
| Core → Android | `device.action_result_ack` | `correlation_id` = result envelope `message_id` |
| Core → Android | `device.action_cancel` | `correlation_id` = command envelope `message_id`; stable cancel envelope |
| Android → Core | `device.action_cancel_ack` | `correlation_id` = cancel envelope `message_id` |

Every message remains inside the protocol `1.0` envelope and is rejected when its protocol version, device identity, UUID shape, byte limit, or typed payload is invalid.

## Command acknowledgement statuses

- `accepted`: the encrypted ledger was written and an executor accepted ownership.
- `duplicate`: the same command is active or already completed.
- `busy`: another action or unacknowledged result owns the single-flight slot.
- `expired`: the deadline elapsed before Android accepted the command.
- `rejected`: validation, ledger state, or executor availability prevented acceptance.

An acknowledgement proves receipt state only. It does not prove that the requested visible state was reached.

## Core action broker

Core stores bounded process-local records keyed by `(device_id, action_id)`.

```text
queued → delivered → accepted → completed
                     └────────→ cancelled
queued/delivered/accepted → cancelling → completed/cancelled
queued/delivered/accepted → rejected/expired
```

The broker enforces:

- one active record per device;
- unique `command_id` ownership within a device;
- immutable command content for a reused `action_id`;
- exact command envelope replay after reconnect;
- command, cancellation, and result correlation;
- rejection of messages from an obsolete replaced session;
- bounded terminal history;
- duplicate result acceptance only when the full typed result is identical.

The current broker is in memory. Durable server-side workflow state is a later milestone; the Android write-ahead ledger is already durable because it protects the side-effect boundary itself.

## Android encrypted write-ahead ledger

Before calling `AndroidActionHandler.submit`, Android stores:

```text
schema_version
command_envelope_id
command_hash
command
phase = active
```

Storage properties:

- AES-GCM authenticated encryption;
- non-exportable AES key generated in Android Keystore;
- ciphertext and IV only in private SharedPreferences;
- synchronous `commit()` before executor submission;
- strict schema and command normalization validation on every read.

After completion, the same record is atomically replaced with:

```text
phase = completed
result_message_id
result
result_acknowledged = false
```

The result message ID is generated once and persisted. Reconnects and retries reuse it.

## Restart semantics

### Restart before executor submission

The ledger write completed but execution ownership may not have transferred. Android cannot prove that the side effect did not start, so it does not replay it.

### Restart during or after execution

The same uncertainty exists. When the exact command is redelivered, Android converts the active ledger entry to a terminal result:

```text
outcome = blocked
failure_code = internal_error
attempts = 0
detail = execution state was unknown after Android process restart;
         command was not re-executed
```

This is a deliberate at-most-once bias. A later operation may inspect fresh UI state and safely create a new command, but the transport never guesses.

### Restart after completion but before result acknowledgement

Android reloads the completed record and retransmits the exact result envelope. No device action is re-executed.

## Result publisher

`ActionResultPublisher` owns one result delivery at a time:

- maximum three sends per connection;
- ten-second acknowledgement timeout;
- exact message and correlation IDs across retries;
- failed socket send does not consume an attempt;
- disconnect resets the per-connection attempt budget;
- reconnect resumes the persisted result;
- a competing result cannot replace the active delivery;
- only a matching command ID, action ID, and result message correlation can clear it.

For `accepted` or `duplicate`, Android first persists `result_acknowledged=true`, then clears the publisher. For `unknown_action` or `rejected`, the network delivery is paused but the ledger remains unacknowledged for diagnosis and controlled recovery.

## Cancellation

Cancellation is cooperative, not a rollback guarantee.

1. Core stores one stable cancel envelope and sends it to the current session.
2. Android validates command/action identity against its ledger.
3. If a matching in-process executor exists, `cancel()` is invoked.
4. Android responds with `accepted`, `duplicate`, `not_found`, or `completed`.
5. The executor still owns the final typed action result.

A cancellation request cannot prove that a side effect already accepted by another application was reversed.

## WebSocket integration

`CoreWebSocketClient` routes inbound action commands, cancellations, and result acknowledgements to `SimorghConnectionService`. The service owns:

- `AndroidActionRouter`;
- `PersistentActionLedger`;
- `ActionResultPublisher`;
- command and cancellation acknowledgements;
- recovery of an unacknowledged result at process start and reconnect.

Unknown inbound message types, oversized UTF-8 payloads, invalid protocol versions, wrong device identities, malformed UUIDs, and typed payload decoding failures fail closed.

## Failure matrix

| Failure | Behavior |
|---|---|
| Device offline during dispatch | Core record remains queued; original envelope is sent after registration |
| Disconnect after command delivery | Original command envelope is redelivered after reconnect |
| Duplicate active command | Android returns `duplicate`; executor is not called again |
| Android process dies with active ledger | A blocked recovery result is emitted; command is not replayed |
| Result ACK is lost | Exact result envelope is retransmitted |
| Result is replayed to Core | Core returns `duplicate` only when content is identical |
| Different content reuses an identifier | Conflict; state is not overwritten |
| Corrupt encrypted ledger | Command is rejected before executor invocation |
| Competing action arrives | `busy`/HTTP 409; existing action retains ownership |
| Oversized message | Rejected/connection closed with message-too-big semantics |
| Executor unavailable | Android returns `rejected` |

## Tests required for this boundary

### Core

- operator credential isolation;
- dispatch, command ACK, result, and result ACK;
- duplicate result handling;
- exact command replay after reconnect;
- per-device single flight;
- cancellation correlation;
- identifier/content conflicts;
- obsolete session rejection.

### Android JVM

- ledger exists before handler submission;
- active duplicate is not submitted twice;
- synchronous completion is not lost;
- restart converts uncertain active state to a blocked result;
- unacknowledged result blocks the next command;
- mismatched result ACK cannot release the ledger;
- corrupt ledger fails closed;
- result retry preserves message and correlation IDs;
- failed send resumes on reconnect without consuming an attempt;
- competing result cannot replace an active delivery;
- protocol command/result/cancel correlation round trips.

### Physical Galaxy A53

Before issue #5 can be closed, record:

- Android and One UI versions;
- service and Accessibility status;
- device registration and advertised capabilities;
- command envelope ID, command ID, and action ID;
- command ACK;
- forced network disconnect and reconnect behavior;
- forced process termination in each ledger phase;
- result and result ACK;
- confirmation that no uncertain action executes twice.

## Current boundary

This document describes transport, persistence, replay, and cancellation semantics only. No app launch, click, text entry, scroll, gesture, or global action is enabled by this increment.

The next vertical slice installs a real handler for only `open_app`, requires a fresh observation precondition, launches one package, waits for a newer observation, verifies `active_package_equals`, and emits a typed result. Other operations remain rejected until separately implemented and tested.
