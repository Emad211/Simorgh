# ADR 0010: Enforced Android action capability negotiation

- Status: Accepted
- Date: 2026-07-24

## Context

Android registration already advertises versioned capabilities such as:

```text
android.open_app.execution.v1
```

Before this decision, Core treated that list as diagnostic metadata. A typed command could be created and delivered to any connected Android Session, with Android expected to reject an operation whose executor was not installed.

That behavior failed several engineering requirements:

1. a Pydantic operation type existing in the shared schema was implicitly treated as dispatch permission;
2. unsupported commands crossed the network and entered Android command/ledger handling unnecessarily;
3. action and command identifiers could be reserved even when no current device could execute them;
4. a device downgrade could receive replay of a command from a newer app version;
5. disconnected and capability-incompatible devices were not distinguishable through a typed operator response;
6. Core did not make the current replacement Session's capability set authoritative.

## Decision

Core will enforce a versioned `AndroidOperation -> required capability set` mapping before action broker ownership and before every command redelivery.

### Live mapping

The initial enabled mapping is:

```text
open_app -> android.open_app.execution.v1
```

No mapping is defined for operations whose side-effect executor is not enabled, even when their data types already exist in the schema.

In particular, schema types such as `click_node`, `set_text`, `scroll_node`, `global_action`, and `wait` do not become dispatchable until their own reviewed executor increment advertises a distinct versioned capability.

### Initial dispatch ordering

For a new action, Core performs:

```text
schema validation
    ↓
cross-field semantic validation
    ↓
live operation capability mapping
    ↓
current connected Session lookup
    ↓
required capability comparison
    ↓
command/action conflict and single-flight checks
    ↓
command envelope creation and broker ownership
    ↓
current-Session revalidation
    ↓
network delivery
```

Failure before envelope creation does not reserve `command_id` or `action_id`. The caller may use the same exact identifiers after a compatible Session registers.

### Typed operator errors

The action endpoint returns structured error details.

Disconnected device:

```json
{
  "code": "device_not_connected",
  "message": "device is not connected",
  "operation_kind": "open_app",
  "required_capabilities": [],
  "missing_capabilities": [],
  "available_capabilities": []
}
```

Connected incompatible device:

```json
{
  "code": "unsupported_device_capability",
  "message": "current device session lacks required capability: android.open_app.execution.v1",
  "operation_kind": "open_app",
  "required_capabilities": ["android.open_app.execution.v1"],
  "missing_capabilities": ["android.open_app.execution.v1"],
  "available_capabilities": ["device.action_transport.v1"]
}
```

Schema operation without a live executor:

```json
{
  "code": "unsupported_operation",
  "message": "Android operation 'wait' is not enabled for Core dispatch",
  "operation_kind": "wait",
  "required_capabilities": [],
  "missing_capabilities": [],
  "available_capabilities": []
}
```

Device-state errors use HTTP `409`. An operation without a live Core dispatch mapping uses HTTP `422`.

### Current Session is authoritative

Core reads capabilities from the currently registered `DeviceSession`, never from:

- SDK version inference;
- a previous Session;
- a stored device profile;
- model output;
- operation-name heuristics.

If Session A advertises `open_app` and Session B replaces it without that capability, Session B is authoritative for new dispatch.

Core re-resolves the current Session during delivery so a replacement between preflight and send cannot be treated as the originally validated Session.

### Reconnect and downgrade behavior

A non-terminal action can already have crossed the device boundary before reconnect.

Core therefore distinguishes two cases.

#### Never delivered

If the record has zero deliveries and no command ACK, an incompatible replacement Session can safely make the action terminally rejected. No Android process could have observed it.

#### Delivery may have occurred

If delivery count is non-zero or Android accepted the command, capability downgrade does **not** prove the side effect never ran. Core:

- does not redeliver the command to the incompatible Session;
- preserves the original phase;
- records a diagnostic detail;
- waits for a valid result or the existing command deadline;
- never creates a replacement command implicitly.

This is an at-most-once bias. It prevents a downgrade from converting “execution uncertain” into a false “not executed” claim.

Cancellation remains a separate transport message. This ADR controls execution-command dispatch, not the generic cancellation contract for an action that may already exist on the device.

### Stable identifiers and retries

When initial negotiation fails, no broker record exists. The same command/action identifiers can be retried after a compatible Session registers.

When a record already exists, the existing identifier and exact command-envelope replay rules remain in force. Capability negotiation does not create a new envelope or silently rewrite the command.

## Consequences

### Positive

- unsupported commands never enter Android action handling;
- device and operator error states are machine-readable;
- schema evolution is decoupled from executor enablement;
- current Session capabilities are enforced rather than displayed;
- app upgrades can enable operations without server-side SDK inference;
- app downgrades cannot receive commands they no longer advertise;
- failed initial negotiation does not poison identifier reuse;
- uncertainty after prior delivery remains explicit and fail-closed;
- each future operation must define its own versioned execution capability.

### Negative

- a connected device can reject an otherwise valid schema command because its app version is older;
- capability rollout requires coordinated Android registration and Core mapping changes;
- an action delivered before downgrade can remain non-terminal until result or deadline;
- callers must handle structured `409` and `422` responses;
- capability checks do not replace action result verification or Android's local contract validation.

## Rejected alternatives

### Let Android reject unsupported commands

Rejected because unsupported commands would still cross the network, reserve broker identity, and enter the encrypted device ledger path.

### Infer capabilities from Android SDK level

Rejected because executor availability depends on Simorgh app code and contract version, not only platform API level.

### Treat every schema operation as dispatchable

Rejected because schema types are introduced before side-effect executors so contracts and selectors can be reviewed independently.

### Cache capabilities outside the current Session

Rejected because a device can upgrade, downgrade, reinstall, or reconnect with a different application build.

### Mark every downgraded in-flight action rejected

Rejected because prior delivery or ACK loss means the side effect may already have run.

### Generate a replacement command after downgrade

Rejected because it would violate stable identity and at-most-once execution bias.

## Validation

Automated tests cover:

- `open_app` mapping to one versioned capability;
- unmapped schema operation rejection;
- disconnected device typed error;
- connected Session missing execution capability;
- no command leakage on rejected dispatch;
- no broker record after initial negotiation failure;
- reuse of the same identifiers after compatible registration;
- latest replacement Session capability authority;
- no redelivery to a downgraded Session;
- accepted action preserved without re-execution after downgrade;
- existing command ACK, cancellation, result, and replay tests under compatible registration.

Physical Galaxy A53 validation is not required to prove Core capability filtering, but future operation capabilities still require their normal physical executor validation before being advertised as supported.
