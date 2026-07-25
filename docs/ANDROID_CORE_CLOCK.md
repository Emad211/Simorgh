# Android bounded Core clock

Status: implemented for Android action admission, `open_app` execution boundaries, observation age, and result timestamps.

## Why this exists

Core sends absolute epoch timestamps, but an Android phone has its own independently adjustable wall clock. Simorgh must not authorize a side effect by comparing those clocks directly.

Android therefore estimates Core epoch from authenticated registration and heartbeat round trips and anchors the estimate to `SystemClock.elapsedRealtime()`.

## Capability

A compatible Android registration advertises:

```text
android.core_clock.bounded_estimate.v1
```

Core requires it together with:

```text
android.open_app.execution.v1
```

A connected phone lacking the clock capability receives the existing typed `unsupported_device_capability` response; no command envelope is created or delivered.

## Registration sequence

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

The possible offset is:

```text
[S - t1, S - t0]
```

The connection becomes `CONNECTED` only after:

- the registration payload is valid;
- the correlation ID matches the exact registration probe;
- the clock sample is accepted;
- a stable bounded reading exists.

## Heartbeat maintenance

Each heartbeat stores:

```text
message_id
sequence
sent_at_elapsedRealtime
connection_generation
```

The ACK must match message ID and sequence. Pending probes are bounded to prevent unbounded memory use.

Behavior:

| Condition | Result |
|---|---|
| exact correlated ACK | sample incorporated |
| unknown or evicted old ACK | ignored, non-fatal |
| missing/non-UUID correlation | protocol failure |
| sequence mismatch | protocol failure |
| old WebSocket generation | ignored |
| large Core interval discontinuity | estimate unstable until confirmation |

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

The midpoint is useful for timestamps and diagnostics. Authorization always uses `latestCoreTimeMs`.

## Deadline rule

```text
guaranteedRemainingMs = deadline_at_ms - latestCoreTimeMs
```

Execution is denied when:

- there is no stable non-stale estimate;
- the command deadline is invalid;
- the deadline elapsed;
- the remaining midpoint budget is no larger than uncertainty;
- the command `issued_at_ms` is later than the latest possible current Core time;
- the WebSocket/clock generation changes during execution.

Clock-related admission maps to:

- `expired` when the bounded deadline elapsed;
- `rejected` for unavailable clock, uncertainty, future issuance, or discontinuity.

The Android encrypted action ledger is not written when a new command fails clock admission.

## Action lease

The Executor creates one lease and never extends its initial local deadline.

```text
localDeadlineElapsed =
    reading.observedAtElapsedRealtimeMs + guaranteedRemainingMs
```

At each boundary it takes the minimum of:

- the initially accepted local remaining time;
- the latest bounded Core remaining time;
- the operation's requested timeout.

This prevents a later noisy heartbeat from granting more execution time.

## Wall-clock changes

Changing Android date, time, timezone, or automatic-time setting does not change:

- command deadline authorization;
- observation age;
- capture-after-request ordering;
- post-launch ordering;
- action duration;
- result `finished_at_ms - started_at_ms`.

Wall-clock jumps are recorded diagnostically at the next clock sample. They do not move the Core estimate.

## Accessibility timestamps

Wire field:

```text
captured_at_ms
```

Purpose:

- Core audit metadata;
- protocol compatibility;
- persisted observation reference.

Local-only field:

```text
capturedAtElapsedRealtimeMs
```

Purpose:

- maximum observation age;
- fresh-capture ordering;
- pre-launch and post-launch ordering.

The local field is `@Transient`, excluded from JSON and canonical fingerprints. Production snapshot construction always stamps it from `SystemClock.elapsedRealtime()`.

## Reconnect behavior

Every physical socket receives a new clock generation.

On reconnect:

1. old probes are cleared;
2. the old estimate is invalidated;
3. a new registration probe is measured;
4. queued non-side-effect messages may wait;
5. a new action is rejected until a stable estimate exists.

An action lease created under an old generation cannot authorize a future launch boundary.

## High latency

High RTT directly widens the interval. This is intentional.

Example:

```text
RTT = 1000 ms
uncertainty ≈ 500 ms
remaining deadline = 400 ms
```

The action is rejected because uncertainty is larger than the remaining safe budget.

Operationally, use a larger Core command deadline rather than weakening Android's uncertainty rule.

## Diagnostics

The Android service emits protocol events containing:

```text
RTT=<milliseconds>
±<uncertainty milliseconds>
sample=<count>
```

It also reports:

- device wall-clock jump;
- Core clock discontinuity;
- unknown late heartbeat probe;
- registration/heartbeat correlation failure;
- stale or unavailable clock at action admission.

These diagnostics must not include device/operator credentials.

## Testing on Galaxy A53

Before claiming One UI validation, record:

1. Android version;
2. One UI version;
3. security patch;
4. APK commit SHA;
5. Core commit SHA;
6. advertised clock capability;
7. registration RTT and uncertainty;
8. several heartbeat RTTs;
9. phone clock moved at least five minutes forward;
10. phone clock moved at least five minutes backward;
11. automatic time toggled during a waiting action;
12. Wi-Fi/mobile-data transition and reconnect;
13. high-latency or throttled-network case;
14. a deadline shorter than uncertainty, proving no launch occurs;
15. a valid longer deadline, proving normal execution;
16. observation age before and after wall-clock change;
17. result duration based on monotonic elapsed time;
18. no command accepted before clock registration is stable.

## Limitations

- The estimate is between Android and one Simorgh Core connection, not global time synchronization.
- `elapsedRealtime` survives sleep but resets on device reboot.
- Local monotonic capture timestamps are intentionally not persisted across reboot.
- A reconnect temporarily removes execution availability until a new sample is stable.
- Extremely asymmetric network delay remains represented by the conservative interval rather than guessed away.

See ADR 0012 for the decision rationale and rejected alternatives.
