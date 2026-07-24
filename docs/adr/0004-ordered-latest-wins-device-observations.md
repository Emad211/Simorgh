# ADR 0004: Ordered, latest-wins Android observations

- Status: Accepted
- Date: 2026-07-24

## Context

Android Accessibility can produce a burst of structurally similar events for one visible transition. A personal agent needs the latest stable state, not an unbounded event log. At the same time, WebSocket reconnects and acknowledgement loss can replay a message. Treating every replay as new state would make later action verification non-deterministic.

A capture timestamp alone is not sufficient ordering evidence because wall clocks can move and multiple snapshots can share one millisecond. A WebSocket session alone is not sufficient idempotency scope because the connection can be replaced while the device and UI state remain the same.

## Decision

Simorgh will transport Accessibility state as ordered observations with:

- a publisher-lifetime UUID `stream_id`;
- a monotonically increasing `sequence` within that stream;
- a unique `snapshot_id`;
- a retry-stable protocol `message_id`;
- a cross-language canonical SHA-256 state fingerprint;
- a one-in-flight, one-latest-pending Android publisher;
- per-device Core observation state that survives WebSocket replacement within the Core process;
- explicit `accepted`, `unchanged`, `duplicate`, and `stale` acknowledgements.

Core independently validates the complete snapshot and recalculates the state fingerprint. Observation messages bypass the generic reconnect queue because the publisher owns retry, backpressure, and acknowledgement semantics.

## Consequences

### Positive

- Retry after reconnect is idempotent.
- Unchanged state can refresh freshness without appearing as changed UI.
- A stale intermediate screen cannot replace a newer state.
- Android can discard burst intermediates before network transmission.
- Action verification can later reference an explicit ordered observation.
- Python and Kotlin implementations are protected by a shared golden fingerprint vector.

### Negative

- Some intermediate animations and transient UI states are intentionally lost.
- Current deduplication state is lost when Simorgh Core restarts.
- The protocol and tests are more complex than fire-and-forget snapshots.
- A new process creates a new stream and therefore a new observation epoch.

## Rejected alternatives

### Send every Accessibility event

Rejected because event volume is high, many events describe obsolete intermediate states, and planner cost would grow without improving action reliability.

### Use only capture timestamps

Rejected because wall-clock time is not a reliable total ordering primitive.

### Store observation state on the WebSocket session

Rejected because reconnect would erase deduplication and accept a retry as new state.

### Reuse the generic outbound reconnect queue

Rejected because it can retain stale observations and race with the observation publisher's own retry logic.

### Trust the device-provided fingerprint

Rejected because a protocol boundary must verify derived evidence independently.

## Follow-up

A later persistence ADR will define durable device epochs, observation retention, encryption at rest, and replay recovery across Core restarts. The action executor must consume only schema-valid observations from this ordered ledger.
