# Android bounded Core clock

Status: implemented for Android connection admission, action admission, `open_app` execution boundaries, Accessibility evidence ordering, and action-result timestamps.

## Purpose

Simorgh Core sends epoch timestamps such as:

```text
issued_at_ms
deadline_at_ms
server_time_ms
```

The Android phone has an independently adjustable wall clock. Manual changes, network correction, timezone changes, OEM resume behavior, or an inaccurate real-time clock must never authorize or invalidate a side effect.

Android therefore estimates Core epoch from authenticated registration and heartbeat round trips and anchors every local duration to:

```text
SystemClock.elapsedRealtime()
```

## Specialist-agent boundary

Clock normalization is deliberately split into deterministic specialists:

```text
Transport Agent
  CoreClockSynchronizer
  owns probes, message correlation, heartbeat sequence, socket generation

Clock Agent
  CoreClockEstimator + CoreExecutionLease
  owns interval math, uncertainty, deadline budget, monotonic duration

Execution Agent
  AndroidActionRouter + OpenAppActionExecutor
  owns ledger admission, evidence checks, and the launch boundary
```

None of these components calls an LLM, AvalAI, a cloud clock service, or a separate network endpoint.

Operational cost:

- zero model calls;
- zero additional HTTP/WebSocket requests;
- existing registration and heartbeat messages are reused;
- O(1) integer arithmetic per accepted sample;
- at most 32 pending heartbeat probes by default;
- no clock polling loop;
- no clock state persisted to disk;
- no extra field in the Accessibility wire payload.

## Capability

A clock-safe Android build advertises:

```text
android.core_clock.bounded_estimate.v1
```

Core requires both:

```text
android.open_app.execution.v1
android.core_clock.bounded_estimate.v1
```

for `open_app` dispatch. A connected older APK that can launch an app but still depends on device wall time receives a typed `unsupported_device_capability` response. Core does not create or deliver a command envelope.

## Registration sample

```text
Android elapsedRealtime t0
        ↓
device.register message_id = R
        ↓
Core creates device.registered with server_time_ms = S
        ↓
device.registered correlation_id = R
        ↓
Android elapsedRealtime t1
```

Because Core produced `S` between Android send and receive boundaries, the possible Core-to-monotonic offset is:

```text
[S - t1, S - t0]
```

At Android monotonic time `t`, Core time is bounded by:

```text
[t + lower_offset, t + upper_offset]
```

The Android connection becomes `CONNECTED` only when:

- the typed registration response is valid;
- `correlation_id` matches the exact registration message ID;
- the sample belongs to the active physical socket generation;
- the sample is accepted;
- a stable bounded reading exists.

## Heartbeat maintenance

Every existing application heartbeat records:

```text
message_id
sequence
sent_at_elapsedRealtime
physical_socket_generation
```

The ACK must match both correlation ID and sequence.

| Condition | Result |
|---|---|
| exact correlated ACK | incorporate sample |
| unknown, evicted, or very late ACK | ignore, non-fatal |
| non-UUID/missing correlation | protocol failure |
| sequence mismatch | protocol failure |
| callback from obsolete socket generation | ignore |
| large Core interval discontinuity | estimate unstable until confirmation |

Pending heartbeat probes are bounded. Eviction changes only clock precision; it cannot authorize a command.

## Generation isolation

Two generation domains are used intentionally:

- a client-local physical socket generation rejects callbacks from an obsolete socket;
- a process-wide unique estimator generation prevents one `CoreWebSocketClient` instance from invalidating a newer client instance that happened to reuse the same local counter value.

Reconnect or a new client instance invalidates old probes and requires a fresh registration sample before new side effects are admitted.

## Reading fields

A stable reading contains:

```text
generation
earliestCoreTimeMs
estimatedCoreTimeMs
latestCoreTimeMs
uncertaintyMs
sampleAgeMs
lastRoundTripTimeMs
sampleCount
discontinuityCount
wallClockJumpCount
observedAtElapsedRealtimeMs
```

The midpoint is used for diagnostics and action-result epoch timestamps. Authorization never assumes symmetric network latency and uses the complete interval.

## Combining samples

- overlapping offset intervals are intersected;
- a small non-overlap is conservatively unioned to tolerate scheduler/timestamp granularity;
- a large gap is a Core-clock discontinuity;
- after a discontinuity, the replacement interval is retained but unstable;
- a second consistent sample is required before action admission resumes.

## Three-state deadline rule

For deadline `D` and bounded current Core interval `[earliest, latest]`:

```text
D <= earliest
    definitely expired

D > earliest and D <= latest
    expiration is uncertain; reject fail-closed

D > latest
    guaranteedRemainingMs = D - latest
```

Mappings:

```text
definitely expired                → command ACK expired
uncertainty overlaps deadline     → command ACK rejected
clock unavailable/stale/unstable  → command ACK rejected
issued_at later than latest       → command ACK rejected
```

This distinction matters operationally: `expired` means every possible Core time is past the deadline; `rejected` for uncertainty means Android cannot prove enough safe time remains.

The encrypted Android action ledger is not written when a new command fails clock admission.

## Action-scoped execution lease

The Executor creates one lease containing:

```text
clock generation
Core midpoint at lease start
elapsedRealtime at lease start
initial uncertainty
Core deadline
conservative local elapsedRealtime deadline
```

```text
localDeadlineElapsed =
    reading.observedAtElapsedRealtimeMs + guaranteedRemainingMs
```

The initial local deadline is never extended. At every execution boundary Android takes the minimum of:

- initial local remaining time;
- latest bounded Core remaining time;
- operation-requested timeout.

A later heartbeat can narrow, invalidate, or expire a lease, but cannot grant extra execution time.

The lease is checked:

1. before fresh pre-launch capture;
2. after evidence revalidation;
3. immediately before `launcher.launch()`;
4. before post-launch verification.

A generation change before launch prevents the side effect. A change after Android accepted the launch cannot undo it; the result remains conservative and the command is never replayed.

## Evidence deadline

A delayed Core ACK must not invalidate evidence that was captured safely before the deadline. Conversely, late evidence must never become success merely because its ACK arrived.

A successful after-observation must satisfy:

```text
captureElapsed >= leaseStartElapsed
captureElapsed < conservativeLocalDeadlineElapsed
```

The comparison uses the local monotonic capture timestamp, not ACK arrival time and not Android wall time.

Evidence captured exactly at or after the conservative deadline produces a timed-out result, not success.

## Result timestamps

```text
started_at_ms =
    bounded Core midpoint at lease creation,
    never earlier than issued_at_ms

finished_at_ms =
    started_at_ms + elapsedRealtime duration
```

Later wall-clock jumps or Core-estimate changes cannot change the duration. Even the exception path after an accepted launch uses the stored action lease rather than a new estimate.

## Wall-clock changes

Android compares wall-clock delta against monotonic delta only for diagnostics. A large difference increments `wallClockJumpCount` and resets the diagnostic anchor.

Changing Android date, time, timezone, or automatic-time mode does not change:

- command authorization;
- observation age;
- capture-after-request ordering;
- post-launch ordering;
- action timeout;
- result duration.

## Accessibility timestamps

Wire/audit field:

```text
captured_at_ms
```

Local execution field:

```text
capturedAtElapsedRealtimeMs
```

The local field is `@Transient`:

- it is not serialized;
- it adds zero wire bytes;
- it does not alter protocol schema `1.0`;
- it does not alter the canonical UI fingerprint;
- it is meaningful only within one Android boot.

Production snapshot construction injects `SystemClock.elapsedRealtime()`. JVM tests inject deterministic clocks rather than falling back to wall time.

Core also avoids using Android wall time to order before/after evidence. It verifies exact audit metadata, stream sequence, and Core-owned observation receive order.

## High latency

High RTT widens uncertainty intentionally.

Example:

```text
Core interval = [10000, 11000]
deadline = 10600
```

The deadline lies inside the interval. The action is rejected as uncertain because Android cannot prove that Core has not already passed it.

Use a larger Core deadline for legitimate high-latency operation. Do not weaken the uncertainty rule.

## Diagnostics

Protocol events may report:

```text
RTT=<milliseconds>
±<uncertainty milliseconds>
sample=<count>
```

Additional diagnostics include:

- device wall-clock jump;
- Core-clock discontinuity;
- unknown late heartbeat probe;
- registration/heartbeat correlation failure;
- stale or unavailable clock;
- generation change before an execution boundary.

Diagnostics never contain device, operator, or provider credentials.

## Samsung Galaxy A53 validation protocol

Before One UI support is claimed, record:

1. Android version;
2. One UI version;
3. security patch;
4. APK and Core commit SHAs;
5. advertised clock capability;
6. registration RTT and uncertainty;
7. several heartbeat RTTs;
8. phone clock moved at least five minutes forward;
9. phone clock moved at least five minutes backward;
10. automatic time toggled during a waiting action;
11. Wi-Fi/mobile-data transition and reconnect;
12. high-latency or throttled-network case;
13. deadline definitely expired;
14. deadline overlapping uncertainty;
15. longer safe deadline;
16. evidence captured before, at, and after the lease deadline;
17. observation age across wall-clock change;
18. result duration based on monotonic elapsed time;
19. no command accepted before registration clock stability;
20. no old client/socket generation invalidating a newer connection.

## Limitations

- This is Core↔Android connection time normalization, not global clock synchronization.
- `elapsedRealtime` survives sleep but resets on reboot.
- local monotonic capture timestamps are not persisted across reboot;
- reconnect temporarily removes side-effect availability;
- extremely asymmetric network delay remains conservatively represented rather than guessed away;
- physical Galaxy A53 validation is still required.

See ADR 0012 for the decision rationale.