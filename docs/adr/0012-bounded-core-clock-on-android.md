# ADR 0012: Bounded Core clock normalization on Android

- Status: Accepted
- Date: 2026-07-25

## Context

Android actions carry Core epoch timestamps:

```text
issued_at_ms
deadline_at_ms
```

Accessibility observations also carry Android wall-clock metadata. Direct comparison with `System.currentTimeMillis()` is unsafe because the phone clock can differ from Core or jump because of manual edits, network correction, timezone changes, OEM resume behavior, virtualization, or an inaccurate RTC.

Unsafe consequences include:

- accepting a command that Core already considers expired;
- rejecting a command that is still valid;
- treating old evidence as fresh;
- reversing before/after observation order;
- changing action duration while the action runs.

The architecture also requires specialist separation: transport correlation, clock mathematics, and side-effect execution must remain deterministic components rather than model-driven behavior.

## Decision

Android will estimate Core epoch as a bounded interval derived from authenticated registration and heartbeat round trips. All local durations and ordering decisions use `SystemClock.elapsedRealtime()`.

No LLM, provider API, third-party time service, or additional clock request is used.

## Component ownership

```text
CoreClockSynchronizer
    owns request probes, correlation, sequence, socket generation

CoreClockEstimator
    owns interval combination, uncertainty, staleness, discontinuity

CoreExecutionLease
    owns one action's conservative local deadline and result duration

AndroidActionRouter
    owns new-command clock admission before ledger mutation

OpenAppActionExecutor
    owns evidence checks and the immediate launch boundary
```

Each component receives typed inputs and returns typed states. Model output cannot alter interval arithmetic, generation identity, deadline classification, or evidence ordering.

## Clock sample

For one correlated request/response:

```text
Android monotonic send = t0
Core server time       = S
Android monotonic recv = t1
```

Core produced `S` after request receipt and before Android response receipt. Therefore the Core-to-monotonic offset lies in:

```text
[S - t1, S - t0]
```

At Android monotonic time `t`, Core time lies in:

```text
[t + lower_offset, t + upper_offset]
```

The midpoint is diagnostic and is used for result epoch timestamps. Authorization uses the bounded interval and does not assume symmetric latency.

## Registration and heartbeat correlation

Every physical WebSocket attempt receives a local socket generation.

- `device.register` records message ID and monotonic send time;
- `device.registered` must correlate to the exact registration message;
- registration does not complete until a stable clock reading exists;
- heartbeat probes record message ID, sequence, monotonic send time, and socket generation;
- heartbeat ACK must match correlation and sequence;
- pending probes are bounded;
- unknown/evicted late ACK is ignored;
- malformed identity or sequence mismatch is a protocol failure;
- reconnect clears probes and invalidates the old estimate.

The shared estimator also receives a process-wide unique generation. This prevents an obsolete `CoreWebSocketClient` instance from invalidating a newer instance that reused the same local generation number.

## Combining samples

- overlapping intervals are intersected;
- small non-overlap is conservatively unioned;
- a large gap is a Core-clock discontinuity;
- after a discontinuity the new interval is retained but unstable;
- another consistent sample is required before new action admission.

A clock estimate becomes unavailable after a bounded sample age.

## Wall-clock jumps

Android wall time is compared with monotonic elapsed time only to produce diagnostics. A large difference increments a counter and resets the diagnostic anchor.

The Core estimate, action lease, observation age, and result duration remain anchored to `elapsedRealtime` and do not move with the phone clock.

## Three-state deadline authorization

For command deadline `D` and possible current Core interval `[E, L]`:

```text
D <= E
    definitely expired

E < D <= L
    uncertain whether deadline elapsed

D > L
    guaranteed remaining = D - L
```

Android maps:

- definite expiry to `expired` command ACK;
- interval overlap to fail-closed `rejected` ACK;
- unavailable/stale/unstable estimate to `rejected`;
- `issued_at_ms > latestCoreTimeMs` to `rejected`.

A new command that fails clock admission does not acquire the encrypted Android ledger or executor.

## Action-scoped lease

The Executor creates a lease containing:

- estimator generation;
- Core midpoint at lease start;
- Android monotonic start;
- initial uncertainty;
- Core deadline;
- conservative local monotonic deadline.

```text
local_deadline =
    reading_observed_elapsed + (Core deadline - latest Core time)
```

The initial local deadline is immutable and can never be extended by later samples.

At each boundary, the remaining budget is the minimum of:

- initial local remaining time;
- latest bounded Core remaining time;
- requested operation timeout.

The lease is checked before fresh capture, after evidence revalidation, immediately before launch, and before verification.

A generation change before launch prevents the side effect. A change after launch acceptance cannot undo the side effect; Android returns a conservative result and never replays the command.

## Evidence capture deadline

Success depends on capture time, not ACK arrival time.

A successful after-observation must be captured:

```text
capture elapsed >= lease start elapsed
capture elapsed < conservative local deadline
```

A Core ACK may arrive later because of transport latency. Evidence captured at or after the local deadline cannot produce success and maps to timeout.

## Result timestamps

`started_at_ms` is the bounded Core midpoint at lease creation, never earlier than `issued_at_ms`.

`finished_at_ms` is computed as start Core time plus monotonic elapsed duration. Later wall-clock changes or estimate jumps do not alter it.

The executor stores the lease in active execution state so exception handling after accepted launch uses the same monotonic timeline.

## Accessibility time

`captured_at_ms` remains exact wire and audit metadata.

Android additionally retains local-only:

```text
capturedAtElapsedRealtimeMs
```

It is `@Transient`, adds no wire bytes, does not change schema `1.0`, and does not change canonical fingerprints.

Android uses it for observation age, explicit-capture ordering, post-launch ordering, and evidence-deadline checks.

Core does not use Android wall time to establish before/after order. It checks exact stored audit identity, observation sequence, and Core-owned receive order.

## Capability negotiation

Android advertises:

```text
android.core_clock.bounded_estimate.v1
```

Core requires both:

```text
android.open_app.execution.v1
android.core_clock.bounded_estimate.v1
```

before dispatching `open_app`.

This prevents clock-unsafe older APKs from receiving a command even when they contain an app-launch executor.

## Cost and performance

Clock safety reuses messages already required for registration and liveness.

- no additional network request;
- no additional heartbeat frequency;
- no model or provider call;
- O(1) integer work per sample;
- bounded probe map, default 32;
- no periodic screenshot or UI-tree upload;
- no persisted clock database;
- no wire-schema expansion.

The clock path is therefore independent of specialist planning-agent count and model cost.

## Consequences

### Positive

- device wall-clock skew no longer controls side effects;
- definite expiry and uncertainty are distinguishable;
- high RTT is represented rather than hidden;
- reconnect cannot reuse old clock authority;
- old client instances cannot invalidate newer clock state;
- leases never gain time;
- observation freshness and ordering are monotonic;
- successful evidence must be captured before deadline;
- result timestamps remain Core epoch with monotonic duration;
- clock-unsafe APKs are blocked by capability negotiation;
- existing protocol and Accessibility schema remain compatible;
- no recurring model or network cost is added.

### Negative

- registration depends on one valid clock sample;
- reconnect/discontinuity/stale state temporarily disables new side effects;
- high latency can consume short deadlines;
- one action has both a Core absolute deadline and a local conservative lease;
- monotonic capture time resets on reboot and is not durable;
- physical OEM validation is still required.

## Rejected alternatives

### Compare deadlines with Android wall time

Rejected because skew or jumps change authorization.

### Assume symmetric latency and store a point offset

Rejected because mobile uplink/downlink latency can be asymmetric. The interval is the source of truth.

### Use only `envelope.sent_at_ms`

Rejected because it is not tied to the Android send boundary and can contain arbitrary queue delay.

### Add a separate time-sync endpoint or faster heartbeat

Rejected because existing correlated registration and heartbeat traffic provides the required bounds without additional network or battery cost.

### Put monotonic timestamps on the wire

Rejected because Android monotonic time has meaning only within one boot and cannot be compared directly by Core.

### Let uncertainty extend a deadline

Rejected because uncertainty must reduce the safe window.

### Accept while the estimate is unstable

Rejected because the next step may be a real side effect.

### Ask a model whether the command is probably still valid

Rejected because deadline authorization is deterministic safety logic, not a semantic judgment.

## Validation

Automated tests cover:

- positive/negative phone skew;
- interval midpoint and uncertainty;
- high RTT;
- intersected samples;
- definite expiry versus uncertainty overlap;
- wall-clock jumps;
- discontinuity confirmation;
- stale estimate;
- registration correlation;
- heartbeat sequence and bounded probe eviction;
- reconnect and cross-client generation isolation;
- lease non-extension;
- generation change before launch;
- rejection before ledger ownership;
- raw wall time ignored for freshness;
- local monotonic timestamp excluded from wire/fingerprint;
- monotonic result duration, including exception path;
- evidence captured before/at/after deadline;
- Core result ordering by sequence and receive time;
- separate executor/clock capability negotiation.

Physical Samsung Galaxy A53 validation remains separate and must cover wall-clock changes, reconnect, latency, evidence deadline boundaries, advertised capability, and proof that no expired or uncertain command crosses the launch boundary.