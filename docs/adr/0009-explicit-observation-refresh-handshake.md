# ADR 0009: Explicit observation refresh handshake

- Status: Accepted
- Date: 2026-07-24

## Context

Android action preconditions intentionally use a strict observation-age budget. The normal observation publisher intentionally suppresses unchanged canonical UI state.

Together, those correct behaviors create a liveness gap:

1. the visible screen remains unchanged and still correct;
2. its last Core acknowledgement becomes older than the action freshness budget;
3. normal publication suppresses the same canonical state;
4. Core cannot safely bind a new action to recent evidence;
5. increasing `maximum_age_ms` would weaken stale-state protection.

Simorgh therefore needs an explicit, bounded mechanism that asks Android to capture the current screen again, while preserving ordinary state deduplication and all existing action safety rules.

## Decision

Simorgh will implement a typed observation-refresh protocol independent of action execution.

### Message flow

```text
trusted operator API
        |
        v
device.observation_refresh
        |
        v
Android validates request identity and observer availability
        |
        v
device.observation_refresh_ack
        |
        +---- unavailable / busy / rejected ----------> terminal refresh state
        |
        v
explicit Accessibility capture
        |
        v
forced device.observation
correlation_id = refresh request message_id
        |
        v
Core registry validation + compact evidence storage
        |
        v
device.observation_ack
        |
        v
Core refresh record = completed
```

Refresh identity is transport metadata carried by `correlation_id`. It is not added to the Accessibility snapshot or canonical UI fingerprint.

### Protocol identity

The request envelope and payload share one UUID:

```text
envelope.message_id == payload.request_id
```

The Android acknowledgement must satisfy:

```text
ack.correlation_id == request.message_id
ack.payload.request_id == request.message_id
```

The correlated observation satisfies:

```text
observation.correlation_id == request.message_id
```

Retries and reconnect redelivery preserve the exact request or observation envelope, including its message ID and payload.

### Core request payload

The request contains:

- `request_id`;
- relative `timeout_ms` in `250..10000`;
- optional expected canonical fingerprint;
- optional expected active package;
- bounded diagnostic reason.

Android uses the relative timeout with its local monotonic scheduler. It does not compare a Core wall-clock deadline against device wall time.

Core independently stores an absolute expiry for record lifecycle and reconnect redelivery.

### Android acknowledgement

Android emits a typed acknowledgement:

- `accepted`: the coordinator owns a new capture request;
- `duplicate`: the same request already owns capture, delivery, or recent acknowledged history;
- `busy`: another refresh owns the single-flight path;
- `expired`: no new snapshot arrived within the local timeout;
- `observer_unavailable`: the Accessibility observer or capture requester is unavailable;
- `rejected`: request validation, publisher state, or transport-size validation failed.

An accepted ACK is not freshness proof. Only a correlated observation that Core records and acknowledges can complete the refresh.

Android may emit a terminal ACK after its initial accepted ACK. Core may also expire the record first. Once Core reaches a terminal state, that state is authoritative: a later same-request Android ACK is identity-checked and ignored without reopening or rewriting the record.

### Capture coordinator

Android uses one single-flight capture coordinator:

1. validate request identity and timeout bounds;
2. reject or deduplicate competing ownership;
3. verify that Accessibility is connected;
4. record the current snapshot ID;
5. schedule a bounded local timeout;
6. request immediate capture from `SimorghAccessibilityService`;
7. accept only a subsequently published snapshot with a different ID;
8. apply the same privacy projection used by normal transport;
9. submit the projected snapshot to the publisher's priority refresh slot.

Concurrent ordinary Accessibility events may satisfy the request when they are published after ownership and contain a new snapshot ID. They still represent current device state.

The optional expected fingerprint and package are checked by Core, not used to suppress Android publication. This is deliberate: if the screen changed, Core must still learn and acknowledge the new ordinary device state even though the refresh request itself is rejected.

### Forced observation publisher

The observation publisher has:

- one ordinary latest-wins pending slot;
- one priority refresh pending slot;
- one in-flight delivery.

Rules:

- ordinary unchanged state remains deduplicated;
- a refresh bypasses canonical-state deduplication;
- only one refresh is pending or in flight;
- an existing in-flight ordinary observation finishes first;
- a fresh captured refresh supersedes older unsent ordinary state;
- after the in-flight delivery completes, refresh has priority;
- a normal observation cannot replace the refresh;
- retries reuse the exact materialized envelope;
- reconnect resumes the exact in-flight delivery;
- minimum send interval and maximum message size still apply;
- an oversized rejected snapshot is not retained as a reconnect replay candidate.

Sequence numbers are assigned only when a pending state is materialized for actual delivery. Replaced pending states do not consume sequence numbers, and refresh priority cannot create an out-of-order sequence.

Transport-size preview uses the serialized width of `Long.MAX_VALUE`, so a payload accepted near the byte limit cannot later exceed it only because its sequence number grew.

### Core refresh broker

Core maintains one non-terminal refresh per device with phases:

- `queued`;
- `delivered`;
- `accepted`;
- `completed`;
- `rejected`;
- `expired`;
- `cancelled`.

The request envelope is stable across reconnect. Delivery ownership belongs to the latest Session ID that received the request.

Session race rules:

- a Create that loses its Session before any replacement delivery marks the inserted record rejected, so the device is not left permanently busy;
- if a replacement Session already owns or completed the same request, the old Create path preserves that newer ownership;
- a redelivery call from an obsolete Session is a no-op;
- a replacement Session lacking `android.observation.refresh.v1` terminally rejects the active refresh;
- messages from a Session that does not own current delivery are rejected as conflicts.

Network send failure returns the record to `queued`, except that an already accepted record remains accepted. The exact envelope is retried after reconnect.

### Core completion

A correlated observation can complete a non-terminal refresh only when:

- it comes from the Session that owns current delivery;
- the record is `delivered` or `accepted`;
- registry status is not `stale`;
- optional expected fingerprint and package match;
- exact compact evidence exists in Core's acknowledged-observation history.

The gateway order is:

1. validate and store the observation;
2. prepare a completion candidate;
3. send `device.observation_ack` on the serialized Session socket;
4. commit the refresh as `completed`.

Sending the ACK first prevents a subsequent action command from overtaking the evidence acknowledgement on the same WebSocket.

If sending the ACK fails, Android retries the exact observation after reconnect. Core then resolves the same compact evidence and can complete the still-active refresh.

### Operator API

Core exposes:

```text
POST /v1/devices/{device_id}/observation-refreshes
GET  /v1/devices/{device_id}/observation-refreshes/{request_id}
POST /v1/devices/{device_id}/observation-refreshes/{request_id}/cancel
```

Create returns `202` with a stable request ID. Callers poll until a terminal phase.

A completed response includes compact evidence:

- observation message ID;
- Session ID;
- Core acknowledgement time;
- stream ID;
- sequence;
- snapshot ID;
- state fingerprint;
- capture time;
- active package.

An orchestrator uses the result as follows:

1. create refresh;
2. wait for `completed`;
3. construct a new `AndroidActionCommand` bound to the returned evidence;
4. dispatch that action without relaxing `maximum_age_ms`.

The raw action API and caller-supplied command identity remain unchanged.

### Capability requirement

A refresh requires:

```text
android.observation.refresh.v1
```

Core creates a request only for a current connected Session advertising that versioned capability. The same requirement is applied to replacement Sessions during redelivery.

### Cancellation

Cancellation is Core-side and terminal. A late ACK or correlated observation cannot reopen or complete a cancelled record.

A late correlated observation is still validated, stored, and acknowledged as ordinary device state. It simply has no refresh completion candidate.

No device-side cancellation message is required because capture is observation-only and bounded by a short local timeout.

### Restart semantics

The refresh broker is process-local in this increment:

- reconnect within one Core process redelivers the exact request;
- Core process restart loses non-terminal refresh records;
- a late correlated observation after restart remains valid ordinary state but cannot complete an unknown refresh;
- the caller safely creates a new refresh.

Refresh has no external side effect, so creating a replacement request is safe. Durable action/result recovery remains issue #22.

## Consequences

### Positive

- unchanged screens produce fresh strict evidence on demand;
- action freshness remains strict;
- normal observation traffic remains deduplicated and bounded;
- refresh delivery cannot be displaced by ordinary UI churn;
- sequence ordering remains monotonic without gaps from replaced pending state;
- request, ACK, and observation correlation are explicit;
- exact reconnect replay is safe;
- expected-state mismatch still updates Core's ordinary device state;
- Core/Android timer races do not create false protocol conflicts;
- stale Session races cannot permanently lock the device;
- Android uses local relative time instead of cross-device wall-clock comparison;
- action transport and identifiers remain unchanged.

### Negative

- one planning cycle gains an additional network round trip;
- one priority slot and capture coordinator add state-machine complexity;
- refresh can fail when Accessibility is unavailable even if the UI is visible;
- expected-state mismatch completes ordinary observation transport but rejects the refresh goal;
- Core restart requires a new request;
- callers must explicitly bind completed evidence into a new action command;
- physical OEM validation remains necessary.

## Rejected alternatives

### Increase `maximum_age_ms`

Rejected because it weakens stale-plan protection instead of producing fresh proof.

### Disable ordinary observation deduplication

Rejected because a stable screen would continuously transmit large identical trees.

### Add refresh identity to canonical UI state

Rejected because request identity is transport metadata and would corrupt state deduplication semantics.

### Check expected state only on Android and suppress mismatch publication

Rejected because Core must learn the actual current screen when it changed.

### Complete on Android ACK alone

Rejected because accepting capture ownership does not prove Core observed the resulting state.

### Complete before sending observation ACK

Rejected because an action could overtake the evidence acknowledgement.

### Reserve sequence numbers when pending state is queued

Rejected because latest-wins replacement and refresh priority could create gaps or out-of-order delivery.

### Treat late terminal ACK as a conflicting state transition

Rejected because Core and Android use independently bounded timers; Core terminal state is already authoritative.

### Automatically mutate an existing action command

Rejected because command IDs, issue/deadline times, and caller intent must not be silently rewritten. A higher-level orchestration API can be added separately.

## Validation

Automated coverage must include:

- Python and Kotlin protocol round trip;
- unchanged-state forced delivery;
- refresh priority and monotonic sequence assignment;
- exact envelope retry and reconnect;
- duplicate versus competing request;
- observer unavailable and disconnect;
- timeout;
- expected-state mismatch while retaining ordinary observation;
- cancellation followed by late ACK and observation;
- replacement Session ownership and obsolete redelivery;
- failed initial delivery not leaving the device busy;
- Core expiry followed by late Android timeout ACK;
- unknown refresh after broker recreation;
- completed evidence used in a strict action precondition.

Physical Samsung Galaxy A53 validation remains separate and must be recorded before OEM support is claimed.
