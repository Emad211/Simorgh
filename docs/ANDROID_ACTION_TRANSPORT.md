# Android action transport

Status: implemented typed transport with one live verified side effect: `open_app`

## Purpose

This subsystem transports one validated Android action from Simorgh Core to one private Android device and returns one typed result without silently duplicating an uncertain side effect.

The transport does not interpret natural language and does not choose screen coordinates. Core accepts a schema-versioned `AndroidActionCommand`, applies semantic and capability checks, and sends it only to a current device Session that advertises the operation's enabled execution capability.

Android validates the command again, writes it to an encrypted ledger, and delegates it to exactly one installed executor.

## Non-negotiable invariants

1. One device has at most one non-terminal action.
2. Schema availability is not execution permission.
3. Every live operation maps to an explicit versioned device capability.
4. Initial dispatch requires a current connected Session advertising that capability.
5. Negotiation failure occurs before command-envelope creation and broker identity ownership.
6. `command_id`, `action_id`, and protocol `message_id` are UUIDs with distinct roles.
7. Reconnect redelivers only the original command envelope and only to a compatible Session.
8. Android writes an encrypted active ledger entry before invoking an executor.
9. Process restart never blindly repeats an action whose execution state is uncertain.
10. A completed result keeps one stable result `message_id` until Core acknowledges it.
11. A new command is blocked while a prior result remains unacknowledged.
12. Action result and observation payloads use dedicated bounded retry state machines.
13. WebSocket writes are serialized per device Session.
14. Model-provider credentials never cross the Core boundary.

## Credentials

```dotenv
SIMORGH_DEVICE_TOKEN=<phone-to-core-websocket-token>
SIMORGH_OPERATOR_TOKEN=<trusted-core-action-api-token>
AVALAI_API_KEY=<core-only-model-provider-key>
```

- `SIMORGH_DEVICE_TOKEN` authenticates the persistent Android WebSocket.
- `SIMORGH_OPERATOR_TOKEN` authorizes action dispatch, status lookup, cancellation, and observation refresh APIs.
- `AVALAI_API_KEY` remains on Core and is unrelated to device authentication.
- Device, operator, and model-provider credentials are not interchangeable.

The shared development device token is not the final pairing design. Per-device revocable credentials remain a later increment.

## Operator API

```http
POST /v1/devices/{device_id}/actions
GET  /v1/devices/{device_id}/actions/{action_id}
POST /v1/devices/{device_id}/actions/{action_id}/cancel
Authorization: Bearer <SIMORGH_OPERATOR_TOKEN>
```

`POST /actions` accepts only `AndroidActionCommand`. Raw natural-language instructions never cross the execution boundary.

## Capability negotiation

Android registration contains a versioned capability list. Core enforces the current Session's list rather than inferring support from SDK level or a historical device profile.

Initial live mapping:

```text
open_app -> android.open_app.execution.v1
```

The shared schema also contains operation types reserved for later reviewed increments. Until their executors and capabilities are enabled, Core rejects them as `unsupported_operation` and does not create an action record.

### Dispatch ordering

```text
schema validation
    ↓
cross-field semantic validation
    ↓
operation → capability mapping
    ↓
current Session lookup
    ↓
capability comparison
    ↓
identifier and single-flight checks
    ↓
command envelope creation
    ↓
current-Session revalidation
    ↓
delivery
```

### Typed negotiation errors

Disconnected current device:

```json
{
  "detail": {
    "code": "device_not_connected",
    "message": "device is not connected",
    "operation_kind": "open_app",
    "required_capabilities": [],
    "missing_capabilities": [],
    "available_capabilities": []
  }
}
```

Connected Session missing execution capability:

```json
{
  "detail": {
    "code": "unsupported_device_capability",
    "message": "current device session lacks required capability: android.open_app.execution.v1",
    "operation_kind": "open_app",
    "required_capabilities": ["android.open_app.execution.v1"],
    "missing_capabilities": ["android.open_app.execution.v1"],
    "available_capabilities": ["device.action_transport.v1"]
  }
}
```

Known schema operation without a live executor:

```json
{
  "detail": {
    "code": "unsupported_operation",
    "message": "Android operation 'wait' is not enabled for Core dispatch",
    "operation_kind": "wait",
    "required_capabilities": [],
    "missing_capabilities": [],
    "available_capabilities": []
  }
}
```

Device-state conflicts use HTTP `409`; an operation without a live Core mapping uses HTTP `422`.

Initial negotiation failure reserves no action or command identifier. The exact same command can be submitted after a compatible Session registers.

See ADR 0010: [`adr/0010-enforced-android-action-capabilities.md`](adr/0010-enforced-android-action-capabilities.md).

## Wire messages

| Direction | Type | Correlation rule |
|---|---|---|
| Core → Android | `device.action_command` | Stable command-envelope `message_id` |
| Android → Core | `device.action_command_ack` | `correlation_id` = command-envelope `message_id` |
| Android → Core | `device.action_result` | `correlation_id` = command-envelope `message_id`; stable result `message_id` |
| Core → Android | `device.action_result_ack` | `correlation_id` = result-envelope `message_id` |
| Core → Android | `device.action_cancel` | `correlation_id` = command-envelope `message_id`; stable cancel envelope |
| Android → Core | `device.action_cancel_ack` | `correlation_id` = cancel-envelope `message_id` |

Every message remains in protocol envelope `1.0` and is rejected when its protocol version, device identity, UUID shape, byte limit, or typed payload is invalid.

## Command acknowledgement statuses

- `accepted`: encrypted ledger was written and an executor accepted ownership.
- `duplicate`: exact command is active or already completed.
- `busy`: another action or unacknowledged result owns the Android slot.
- `expired`: deadline elapsed before Android accepted ownership.
- `rejected`: validation, ledger state, or executor availability prevented acceptance.

An ACK proves receipt state only. It does not prove that the requested visible state was reached.

## Core action broker

Core stores bounded process-local records keyed by `(device_id, action_id)`.

```text
queued → delivered → accepted → completed
                     └────────→ cancelled
queued/delivered/accepted → cancelling → completed/cancelled
queued/delivered/accepted → rejected/expired
```

The broker enforces:

- current-Session connectivity and execution capability before new ownership;
- one active record per device;
- unique `command_id` ownership within a device;
- immutable command content for reused `action_id`;
- exact envelope replay after reconnect;
- capability revalidation before command redelivery;
- command, cancellation, and result correlation;
- rejection of messages from obsolete replaced Sessions;
- bounded terminal history;
- duplicate result acceptance only when the complete typed result is identical.

### Upgrade and downgrade behavior

The newest registered Session is authoritative for new actions.

If a command has never crossed the device boundary and a replacement Session lacks its capability, Core may reject it safely.

If delivery count is already non-zero or Android accepted the command, a downgrade does not prove the side effect never ran. Core therefore:

- does not send the command to the incompatible replacement Session;
- preserves the existing phase;
- records a diagnostic detail;
- waits for a result or the original deadline;
- never creates a replacement command implicitly.

This preserves the at-most-once bias under ACK loss and app downgrade.

The Core broker remains process-local. Durable Core action journal and orphaned-result recovery are tracked separately in issue #22.

## Android encrypted write-ahead ledger

Before `AndroidActionHandler.submit`, Android stores:

```text
schema_version
command_envelope_id
command_hash
command
phase = active
```

Properties:

- AES-GCM authenticated encryption;
- non-exportable AES key generated in Android Keystore;
- ciphertext and IV in private SharedPreferences;
- synchronous `commit()` before executor submission;
- strict schema and normalization validation on every read.

After completion, the record is atomically replaced with:

```text
phase = completed
result_message_id
result
result_acknowledged = false
```

Result identity is generated once and persisted. Reconnect and retry reuse it.

## Restart semantics

### Restart before, during, or immediately after executor submission

Android cannot prove that the side effect did not start. It does not replay the action. Recovery produces:

```text
outcome = blocked
failure_code = internal_error
detail = execution state was unknown after Android process restart;
         command was not re-executed
```

This is an intentional at-most-once bias.

### Restart after completion but before result acknowledgement

Android reloads the completed record and retransmits the exact result envelope. The device action is not re-executed.

## Result publisher

`ActionResultPublisher` owns one result delivery:

- at most three sends per connection;
- ten-second ACK timeout;
- exact message and correlation IDs across retries;
- failed socket send does not consume an attempt;
- reconnect resets the per-connection attempt budget;
- persisted result resumes after reconnect;
- competing result cannot replace active delivery;
- only matching command, action, and result-message correlation can clear it.

For `accepted` or `duplicate`, Android persists `result_acknowledged=true`, then clears publisher state. For `unknown_action` or `rejected`, network retry stops but the encrypted ledger remains unacknowledged for controlled recovery.

## Cancellation

Cancellation is cooperative, not a rollback guarantee.

1. Core stores one stable cancel envelope.
2. Android validates command/action identity against its ledger.
3. A matching in-process executor receives `cancel()`.
4. Android replies `accepted`, `duplicate`, `not_found`, or `completed`.
5. The executor still owns the final typed result.

Capability negotiation controls execution-command dispatch. Cancellation is a separate transport message for an action that may already exist on the device.

## Failure matrix

| Failure | Behavior |
|---|---|
| Device disconnected during initial dispatch | HTTP 409 `device_not_connected`; no record or envelope |
| Current Session lacks operation capability | HTTP 409 `unsupported_device_capability`; no record or envelope |
| Operation has no live executor mapping | HTTP 422 `unsupported_operation`; no record or envelope |
| Compatible Session disconnects after command delivery | Exact command may be redelivered only to another compatible Session |
| Replacement Session lacks capability before any delivery | Action can become rejected safely |
| Replacement Session lacks capability after possible delivery | No redelivery; phase retained until result/deadline |
| Duplicate active command | Android returns `duplicate`; executor is not called again |
| Android process dies with active ledger | Blocked recovery result; command is not replayed |
| Result ACK is lost | Exact result envelope is retransmitted |
| Result is replayed to Core | `duplicate` only when content is identical |
| Different content reuses an identifier | Conflict; state is not overwritten |
| Corrupt encrypted ledger | Command rejected before executor invocation |
| Competing action arrives | HTTP 409; current action retains ownership |
| Oversized message | Rejected with message-too-big semantics |
| Executor unavailable despite advertised capability | Android returns `rejected` |

## Automated tests

Core coverage includes:

- operator credential isolation;
- operation-to-capability mapping;
- unmapped operation rejection;
- disconnected and missing-capability typed errors;
- absence of command leakage after negotiation failure;
- identifier reuse after compatible registration;
- current replacement Session authority;
- no redelivery after capability downgrade;
- accepted action preservation after downgrade;
- dispatch, command ACK, result, and result ACK;
- duplicate result handling;
- exact command replay after reconnect;
- per-device single flight;
- cancellation correlation;
- identifier/content conflicts;
- obsolete Session rejection.

Android JVM coverage includes:

- ledger exists before handler submission;
- active duplicate is not submitted twice;
- synchronous completion is retained;
- restart converts uncertain active state to a blocked result;
- unacknowledged result blocks the next command;
- mismatched result ACK cannot release the ledger;
- corrupt ledger fails closed;
- result retry preserves message and correlation IDs;
- failed send resumes after reconnect without consuming an attempt;
- competing result cannot replace active delivery;
- protocol command/result/cancel correlation round trips.

## Physical Galaxy A53 boundary

Capability filtering is a Core behavior and is covered automatically. The `open_app` executor itself still requires the documented physical Galaxy A53 protocol before One UI validation is claimed.

Record at minimum:

- Android and One UI versions;
- app commit and advertised capabilities;
- command and result identities;
- foreground/background launch conditions;
- reconnect and process-death cases;
- proof that no uncertain action executes twice.

## Current boundary

Live action:

```text
open_app(package_name)
open_app(package_name, uri)
```

Other schema operations remain non-dispatchable until they receive:

- an independent executor;
- a versioned capability;
- deterministic tests;
- evidence-bound success semantics;
- physical-device validation where applicable.
