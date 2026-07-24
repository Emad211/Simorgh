# ADR 0009: Explicit observation refresh handshake

- Status: Accepted
- Date: 2026-07-24

## Context

Android action preconditions intentionally use a strict observation-age budget. The normal observation publisher also intentionally suppresses unchanged canonical UI state.

Those two correct behaviors create a liveness gap:

1. the visible screen remains unchanged and still correct;
2. the last Core acknowledgement becomes older than the action freshness budget;
3. normal publishing suppresses another identical state;
4. Core cannot safely bind a new action to fresh evidence;
5. increasing `maximum_age_ms` would weaken stale-state protection.

The system needs an explicit, bounded handshake that obtains newly acknowledged evidence without turning unchanged UI into continuous network traffic.

## Decision

Simorgh will add a typed observation-refresh protocol independent of action execution.

### Message flow

```text
Core operator API
        |
        v
device.observation_refresh
        |
        v
Android validates request and observer availability
        |
        v
device.observation_refresh_ack
        |
        +---- rejected / unavailable / busy ----------> terminal failure
        |
        v
explicit Accessibility capture
        |
        v
forced device.observation
correlation_id = refresh envelope message_id
        |
        v
Core registry validation and evidence storage
        |
        v
device.observation_ack
        |
        v
Core refresh record = completed
```

The ordinary observation payload and canonical fingerprint remain unchanged. Refresh identity is carried by the observation envelope's `correlation_id`, not by UI data.

### Core request payload

The request contains:

- `request_id`, equal to the refresh envelope message ID;
- relative `timeout_ms`;
- optional expected state fingerprint;
- optional expected active package;
- bounded diagnostic reason.

Android uses the relative timeout with a monotonic clock. It does not compare Core wall-clock deadlines to device wall time.

Core retains its own absolute expiry for record lifecycle and redelivery.

### Android acknowledgement

Android immediately emits a typed acknowledgement:

- `accepted`: capture ownership was accepted;
- `duplicate`: the exact request is already active or represented by queued/in-flight delivery;
- `busy`: another refresh owns the single-flight coordinator;
- `expired`: local processing could not begin within the request timeout;
- `observer_unavailable`: Accessibility capture is unavailable;
- `rejected`: malformed or internally inconsistent request.

An accepted ACK is not freshness proof. Only the correlated observation acknowledged by Core is proof.

### Forced observation delivery

The observation publisher gains one priority refresh slot in addition to normal latest-wins state:

- normal pending observations remain latest-wins;
- a refresh observation bypasses canonical-fingerprint deduplication;
- refresh delivery is never replaced by a normal observation;
- only one refresh correlation is pending or in flight;
- an existing normal in-flight observation finishes before the refresh;
- the refresh then has priority over normal pending state;
- retries preserve the exact observation envelope and correlation ID;
- reconnect resumes exact in-flight delivery;
- normal minimum send interval and message-size limits still apply.

This preserves backpressure while allowing one explicit unchanged-state proof.

### Capture coordinator

Android uses a single-flight coordinator:

1. records the current local snapshot ID;
2. registers request ownership;
3. asks the system Accessibility service for an immediate capture;
4. accepts only a subsequently published snapshot with a different ID;
5. projects the snapshot through the same transport projection used by normal observation;
6. checks optional expected fingerprint/package locally;
7. submits a forced correlated observation;
8. times out or fails closed when the observer disappears or no new snapshot arrives.

Concurrent ordinary Accessibility events may satisfy the request if they occur after ownership and produce a new snapshot. They still represent fresh current state.

### Core refresh broker

Core maintains one active refresh per device with phases:

- `queued`;
- `delivered`;
- `accepted`;
- `completed`;
- `rejected`;
- `expired`;
- `cancelled`.

The request envelope identity and payload remain stable across reconnect redelivery. Refresh is observation-only, so recapture after Android process restart is safe; however, exact in-flight observation delivery is preferred when available.

Core completion requires:

- current registered device session;
- matching refresh request correlation;
- observation registry status other than `stale`;
- optional expected fingerprint/package match;
- exact compact evidence present in Core's acknowledged-observation history;
- successful transmission of the observation ACK before the record becomes `completed`.

Sending the ACK first ensures a later action command cannot overtake the acknowledgement on the serialized WebSocket.

### Operator API

Core exposes explicit create, read, and cancel resources:

```text
POST /v1/devices/{device_id}/observation-refreshes
GET  /v1/devices/{device_id}/observation-refreshes/{request_id}
POST /v1/devices/{device_id}/observation-refreshes/{request_id}/cancel
```

The create endpoint returns `202` with a stable request ID. Callers poll until terminal state. A completed response contains compact evidence suitable for constructing a strict `ObservationPrecondition`.

The raw action API remains unchanged. An orchestrator can:

1. create refresh;
2. wait for completed evidence;
3. construct a new action command whose precondition binds to that evidence;
4. dispatch the action.

This avoids silently rewriting caller-supplied action identifiers or deadlines.

### Capability requirement

A refresh requires the versioned device capability:

```text
android.observation.refresh.v1
```

Core creates a refresh only for a currently connected session advertising that capability. Redelivery to a replacement session also requires the capability.

### Cancellation

Cancellation is Core-side and terminal. A late correlated observation remains valid ordinary device state but cannot complete the cancelled refresh. No device-side cancellation message is required because capture has no external side effect and is bounded by a short timeout.

### Restart semantics

A refresh broker is process-local in this increment:

- reconnect within the same Core process redelivers the exact request;
- Core process restart loses non-terminal refresh records;
- a late correlated observation after restart is recorded as ordinary state but cannot complete an unknown refresh;
- the caller safely creates a new refresh after restart.

Refresh has no external side effect, so retry is safe. Durable action recovery remains a separate problem in issue #22.

## Consequences

### Positive

- unchanged screens can produce fresh strict evidence on demand;
- action freshness policy remains strict;
- normal observation traffic remains deduplicated and latest-wins;
- refresh observation cannot be displaced by ordinary UI churn;
- protocol correlation is explicit and replay-safe;
- Android uses monotonic relative time instead of cross-device wall-clock comparison;
- Core ACK ordering prevents action delivery from overtaking evidence acknowledgement;
- cancellation and reconnect behavior are deterministic;
- the raw action transport remains stable.

### Negative

- one action-planning cycle gains an additional network round trip;
- a refresh can fail even when UI is visible if Accessibility capture is unavailable;
- one priority refresh slot adds publisher state-machine complexity;
- process restart requires a new refresh request;
- callers must explicitly bind completed evidence into a new action command;
- physical OEM validation remains necessary.

## Rejected alternatives

### Increase `maximum_age_ms`

Rejected because it weakens protection against stale plans rather than producing fresh proof.

### Disable observation deduplication

Rejected because a stable screen would continuously transmit large unchanged trees.

### Add refresh fields to the canonical snapshot

Rejected because request identity is transport metadata, not UI state, and would incorrectly alter canonical fingerprints.

### Complete refresh on Android ACK alone

Rejected because scheduling a capture does not prove Core observed or acknowledged the resulting state.

### Complete refresh before sending observation ACK

Rejected because a newly dispatched action could overtake the ACK on the same device connection.

### Reuse raw `device.error` for all refresh outcomes

Rejected because observer unavailability, busy state, expiry, and rejection are expected typed protocol outcomes.

### Automatically mutate an existing action command

Rejected because command IDs, issue/deadline times, and caller intent should not be silently rewritten. A higher-level orchestration API can be added later.

## Validation

Required automated coverage:

- protocol round trip on Python and Kotlin;
- unchanged-state forced delivery bypassing dedupe;
- refresh priority over normal pending state;
- exact envelope retry and reconnect;
- duplicate request handling;
- observer unavailable;
- concurrent UI change and expected-state mismatch;
- timeout;
- cancellation followed by late observation;
- replacement session redelivery;
- unknown refresh after Core broker recreation;
- completed evidence used to dispatch a strict action.

Physical Galaxy A53 validation remains separate and must be recorded before OEM support is claimed.
