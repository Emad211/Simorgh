# ADR 0012: Bounded Core clock normalization on Android

- Status: Accepted
- Date: 2026-07-25

## Context

Android action commands carry Core epoch timestamps:

```text
issued_at_ms
deadline_at_ms
```

Accessibility snapshots also carry a wall-clock capture timestamp for transport and audit. Android previously compared these values with `System.currentTimeMillis()`.

That is unsafe because the phone wall clock can differ from Core or move during execution because of:

- manual time changes;
- automatic network/NTP correction;
- timezone configuration;
- OEM resume behavior;
- virtualized or test environments;
- an inaccurate real-time clock.

The consequences include accepting expired commands, rejecting valid commands, misclassifying observation age, and reversing before/after ordering.

## Decision

Android will maintain a bounded estimate of Core epoch time from authenticated registration and heartbeat round trips, while every local duration and ordering decision uses `SystemClock.elapsedRealtime()`.

### Clock samples

For one request:

```text
client send elapsedRealtime = t0
Core server_time_ms         = S
client receive elapsedRealtime = t1
```

Core generated `S` after receiving the request and before Android received the response. Therefore the Core-to-monotonic offset lies in:

```text
[S - t1, S - t0]
```

At local monotonic time `t`, Core time lies in:

```text
[t + lower_offset, t + upper_offset]
```

Android exposes:

- earliest possible Core time;
- midpoint estimate;
- latest possible Core time;
- uncertainty, equal to half the interval width rounded up;
- last round-trip time;
- sample age;
- sample count;
- connection generation;
- discontinuity and wall-clock-jump counters.

This is an interval estimate, not a claim that network delay is symmetric.

### Registration and heartbeat correlation

Every physical WebSocket connection receives a new clock generation.

- `device.register` records a monotonic send probe keyed by its message ID.
- `device.registered` must correlate to that exact message ID.
- each `device.heartbeat` records message ID, sequence, and monotonic send time;
- `device.heartbeat_ack` must match both correlation ID and sequence;
- pending heartbeat probes are bounded;
- an unknown late heartbeat ACK is ignored;
- an identity or sequence mismatch is a protocol failure;
- reconnect invalidates every estimate and probe from the previous socket generation.

The Android connection is not considered registered until the registration response produces a stable clock estimate.

### Combining samples

Overlapping offset intervals are intersected. This narrows uncertainty without assuming symmetric delay.

Slightly non-overlapping intervals are conservatively unioned to tolerate scheduler and timestamp granularity noise.

A large gap is treated as a Core clock discontinuity. The new interval is retained but marked unstable. A second consistent sample is required before commands can use it.

### Wall-clock jumps

Android compares wall-clock delta against `elapsedRealtime` delta only for diagnostics. A large difference increments a wall-clock-jump counter and resets the diagnostic anchor.

The Core estimate itself remains anchored to `elapsedRealtime`; changing the phone wall clock cannot move an active action deadline or result duration.

### Staleness

A clock estimate expires after a bounded age. A stale or unstable estimate is equivalent to no clock estimate for new command execution.

### Deadline authorization

For a command deadline `D`, Android uses the latest possible current Core time:

```text
guaranteed_remaining = D - latest_possible_core_time
```

If `guaranteed_remaining <= 0`, the command is expired.

If the midpoint remaining time is less than or equal to uncertainty, uncertainty consumes the remaining budget and execution fails closed.

### Action-scoped execution lease

When Router admission accepts a new command, the Executor creates an action-scoped lease containing:

- clock generation;
- Core midpoint at lease start;
- local `elapsedRealtime` at lease start;
- initial uncertainty;
- Core deadline;
- conservative local monotonic deadline.

The lease is never extended by later samples. A later heartbeat may narrow the budget, expire it, make the estimate unavailable, or reveal a new generation, but cannot increase the initial local deadline.

The Executor rechecks the lease:

1. before waiting for a fresh pre-launch snapshot;
2. after precondition revalidation;
3. immediately before calling the Android launcher;
4. before post-launch verification.

A generation change before launch prevents the side effect. A change after Android accepted the launch cannot undo it; the result is conservative and the command is never replayed.

### Result timestamps

`started_at_ms` is the bounded Core midpoint at lease creation, never earlier than `issued_at_ms`.

`finished_at_ms` is derived by adding local monotonic elapsed duration to that start value. It does not follow later wall-clock or Core-estimate jumps.

### Observation age and ordering

`captured_at_ms` remains wire/audit metadata.

Android snapshots additionally retain:

```text
capturedAtElapsedRealtimeMs
```

This field is local-only and `@Transient`; it does not alter snapshot schema `1.0`, message size, canonical fingerprint, or Core payload.

Android uses the monotonic capture value for:

- maximum observation age;
- determining whether a snapshot was captured after an explicit refresh request;
- determining whether verification evidence was captured after launch;
- rejecting future monotonic timestamps.

### Capability negotiation

Android advertises:

```text
android.core_clock.bounded_estimate.v1
```

Core requires both:

```text
android.open_app.execution.v1
android.core_clock.bounded_estimate.v1
```

before dispatching `open_app`. An older Android build that can launch apps but lacks bounded clock semantics cannot receive the command.

### Compatibility

The implementation uses APIs available on Android API 24:

- `SystemClock.elapsedRealtime()`;
- standard Kotlin/JVM synchronization;
- existing WebSocket and serialization dependencies.

No wall-clock or timezone API is used for an execution decision.

## Consequences

### Positive

- phone clock skew no longer changes command validity;
- manual or automatic wall-clock jumps do not change action duration;
- high RTT is represented as uncertainty rather than hidden precision;
- short uncertain deadlines fail closed;
- reconnect cannot reuse a previous socket's clock estimate;
- observation age and before/after ordering are monotonic;
- result timestamps remain in Core epoch while durations stay monotonic;
- old clock-unsafe Android versions are blocked by capability negotiation;
- the existing wire protocol and Accessibility schema remain compatible.

### Negative

- registration now depends on a valid correlated clock sample;
- commands can be rejected temporarily after reconnect, discontinuity, or stale estimates;
- a high-latency link can consume a short command deadline;
- one action has both a Core absolute deadline and a local conservative lease;
- local monotonic capture timestamps do not survive Android reboot and are intentionally not durable;
- this does not synchronize clocks for unrelated external services.

## Rejected alternatives

### Compare Core deadlines with `System.currentTimeMillis()`

Rejected because device wall-clock skew and jumps directly alter execution authorization.

### Assume symmetric network delay and store a point offset

Rejected because mobile uplink/downlink delay is often asymmetric. The midpoint is diagnostic; authorization uses the interval's latest possible Core time.

### Use only registration time and never refresh it

Rejected because long-lived connections need bounded age and discontinuity detection.

### Trust `envelope.sent_at_ms` without request correlation

Rejected because it is not tied to an Android send boundary and can include arbitrary queuing delay.

### Add monotonic timestamps to the wire schema

Rejected because Android monotonic time is meaningful only within one boot and cannot be compared directly by Core.

### Let uncertainty extend the deadline

Rejected because uncertainty must reduce the safe execution window, not enlarge it.

### Keep accepting commands while the clock estimate is unstable

Rejected because an operation may cross a real side-effect boundary.

## Validation

Automated tests cover:

- positive and negative phone skew;
- midpoint interval and uncertainty;
- high RTT;
- intersection of multiple heartbeat samples;
- uncertainty consuming remaining deadline;
- wall-clock jumps during execution;
- Core discontinuity requiring confirmation;
- stale estimate rejection;
- reconnect generation invalidation;
- registration correlation mismatch;
- heartbeat sequence mismatch;
- bounded probe eviction and unknown late ACK;
- action lease never extending;
- generation change before launch;
- unavailable clock rejection before Android ledger ownership;
- raw wall capture time ignored for freshness;
- monotonic result duration;
- Core capability negotiation requiring bounded clock support.

Physical Samsung Galaxy A53 validation remains separate. Record wall-clock changes, reconnects, network latency, advertised capabilities, and proof that no expired or uncertain command crosses the launch boundary.
