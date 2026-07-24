# Verified Android `open_app` executor

Status: first live Android side-effect vertical slice

## Purpose

`open_app` opens one installed Android application's front-door activity or one explicit package-scoped URI, then proves the declared visible postconditions from fresh Accessibility evidence.

The implementation is intentionally narrow. Only `OpenAppOperation` owns a side-effect path in this increment. Click, text entry, scrolling, arbitrary gestures, and global Accessibility actions remain rejected until each receives an independent implementation, threat analysis, test fixture, and physical-device validation.

## Non-negotiable invariants

1. Raw natural language never reaches Android execution code.
2. Android validates the typed command again after transport decoding.
3. At most one non-terminal device action exists.
4. No side effect runs from an observation that Core has not acknowledged.
5. A fresh local capture must still match the acknowledged pre-action state.
6. An Android API returning normally is not sufficient evidence of success.
7. Success requires a newer, stable visible state and a matching newer Core acknowledgement.
8. An uncertain action after process death is never blindly replayed.
9. Every result carries typed outcome, failure code, attempts, evidence references, and predicate evidence.

## End-to-end flow

```text
Core REST operator request
        |
        v
typed AndroidActionCommand
        |
        v
device.action_command over authenticated WebSocket
        |
        v
encrypted write-ahead ledger commit
        |
        v
latest Core-acknowledged observation
        |
        v
fresh local capture + canonical fingerprint comparison
        |
        +---- mismatch --------------------------> BLOCKED
        |
        v
postconditions already satisfied?
        |
        +---- yes -------------------------------> SUCCEEDED, attempts=0
        |
        v
Android launch adapter
        |
        v
new local Accessibility samples
        |
        v
stable typed postconditions
        |
        v
matching newer Core acknowledgement
        |
        v
typed action result + durable result delivery
```

## Success definition

The operation succeeds only when all applicable conditions hold:

1. the command is schema-valid and unexpired;
2. a recent Core-acknowledged observation satisfies every declared precondition;
3. a newly requested local capture has the same canonical state fingerprint;
4. the desired postcondition is not already satisfied, or Android accepts one launch request;
5. `stable_samples` newer local snapshots satisfy every predicate with one stable fingerprint;
6. the latest locally observed post-launch snapshot still has that fingerprint;
7. a newer observation with the same fingerprint is acknowledged by Core;
8. the final result records before/after references and predicate outcomes.

Holding the final evidence check under the evidence monitor prevents a newly captured failing snapshot from being present but unprocessed when success is returned.

## Typed operation

```json
{
  "kind": "open_app",
  "package_name": "com.example.app",
  "uri": "example://optional/path"
}
```

Rules:

- `package_name` is mandatory;
- `uri` is optional;
- an explicit URI remains package-scoped with `Intent.setPackage`;
- all other operation discriminators are rejected by the installed handler;
- only one launch attempt is permitted per command.

## Android background activity launch constraint

Opening another application is an Activity start. A foreground service does not itself grant unrestricted background Activity launches.

Simorgh permits a launch request only when at least one locally verifiable condition holds:

```text
Simorgh Activity is visible
        OR
Settings.canDrawOverlays(context) == true
```

If neither condition holds, no launch API is called:

```text
outcome = blocked
failure_code = unsupported_capability
attempts = 0
```

The private Android UI contains a Persian setup card for **Display over other apps**. The settings launcher tries, in order:

1. the app-specific overlay screen;
2. the general overlay-permission screen;
3. the general Android settings screen.

Expected OEM `ActivityNotFoundException` and `SecurityException` failures fall through to the next candidate rather than crashing the UI.

Official references:

- <https://developer.android.com/guide/components/activities/secure-bal>
- <https://developer.android.com/reference/android/provider/Settings#canDrawOverlays(android.content.Context)>

The permission does not prove the launch became visible. OEM and lock-screen behavior are still verified from Accessibility evidence.

## Manifest capabilities

The private operator declares:

```xml
<uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW" />
<uses-permission android:name="android.permission.QUERY_ALL_PACKAGES" />
```

`QUERY_ALL_PACKAGES` supports deterministic discovery of arbitrary installed front-door activities on older Android versions. This private increment does not enumerate or upload the installed-application inventory.

## Launch adapters by Android version

### Android 7–12 / API 24–32

```kotlin
PackageManager.getLaunchIntentForPackage(packageName)
```

The returned explicit Intent receives:

```text
FLAG_ACTIVITY_NEW_TASK
FLAG_ACTIVITY_RESET_TASK_IF_NEEDED
```

A null result maps to:

```text
failure_code = target_not_found
attempts = 0
```

### Android 13+ / API 33+

```kotlin
PackageManager.getLaunchIntentSenderForPackage(packageName)
Context.startIntentSender(..., ActivityOptions)
```

This front-door lookup is not restricted by ordinary package visibility. The implementation maps both of the documented missing-target paths to `target_not_found`:

- `PackageManager.NameNotFoundException` while obtaining the sender;
- `IntentSender.SendIntentException` while invoking it.

Android 13 receives the legacy sender-side background launch opt-in. Android 14+ receives `MODE_BACKGROUND_ACTIVITY_START_ALLOWED`. These options express the sender opt-in only; they do not bypass Android policy.

Official references:

- <https://developer.android.com/reference/android/content/pm/PackageManager#getLaunchIntentSenderForPackage(java.lang.String)>
- <https://developer.android.com/reference/android/content/Context#startIntentSender(android.content.IntentSender,android.content.Intent,int,int,int,android.os.Bundle)>

### Explicit package-scoped URI

```kotlin
Intent(Intent.ACTION_VIEW, uri)
    .setPackage(packageName)
    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
```

A URI requires a non-empty scheme. `ActivityNotFoundException` maps to `target_not_found`; `SecurityException` maps to `action_rejected`. A normal return still requires visible postcondition evidence.

## Observation identity and root precedence

Accessibility events provide package and window hints, but an explicit capture can occur before the newest event metadata arrives. When `rootInActiveWindow` exists, its package and window ID are therefore the source of truth. Event hints are fallback values only when the root is unavailable.

This prevents a fresh target-app tree from being mislabeled with the package name from the preceding screen.

## Minimal self-state projection

Simorgh must be able to prove both transitions:

- from Simorgh into another application;
- from another application back into Simorgh.

Sending the complete internal Simorgh UI would expose connection fields and could create an observation/status feedback loop. Completely excluding self-snapshots, however, makes the transition into Simorgh unverifiable.

The device transport therefore projects a self-snapshot to package presence only:

```text
active_package = ai.simorgh.android
active_window_id = null
root_node_id = null
windows = []
nodes = []
```

The projection preserves capture identity and time but removes internal UI content. Different Simorgh screens produce the same canonical state fingerprint. The same projection function is used by transport and local TOCTOU evidence so the two states remain comparable.

See ADR 0008: [`adr/0008-minimal-simorgh-self-state-observation.md`](adr/0008-minimal-simorgh-self-state-observation.md).

## Precondition evidence

An `AcknowledgedAccessibilityObservation` stores compact immutable evidence:

- stream ID;
- sequence;
- canonical state fingerprint;
- snapshot ID;
- capture timestamp;
- active package;
- Core acknowledgement timestamp.

The command may bind to:

- exact stream ID;
- minimum sequence;
- exact state fingerprint;
- expected active package;
- maximum observation age.

Any mismatch blocks before a launch attempt.

## Explicit fresh capture and TOCTOU protection

After command acceptance, the executor requests an immediate capture from the system Accessibility service. The new snapshot must have:

- a different snapshot ID from the local baseline;
- a capture timestamp at or after the request;
- the same canonical fingerprint as the last Core-acknowledged state.

The capture budget is:

```text
min(2,000 ms, remaining command deadline)
```

A mismatch means the UI changed between planning and execution:

```text
outcome = blocked
failure_code = precondition_failed
attempts = 0
```

## Idempotent already-satisfied behavior

After the fresh fingerprint guard, the complete verification policy is evaluated before launching.

If the desired state already exists:

```text
outcome = succeeded
failure_code = none
attempts = 0
before_observation = latest Core-acknowledged observation
after_observation = same observation
```

This avoids unnecessary task switching and makes replay of an already-achieved goal harmless.

## Post-action evidence

The evidence source maintains bounded process-local history:

- latest 32 projected local snapshots;
- latest 64 compact Core acknowledgements.

After Android accepts a launch, it:

1. requests fresh captures periodically;
2. ignores the pre-action snapshot;
3. ignores captures older than launch acceptance;
4. evaluates all typed predicates;
5. requires consecutive stable samples with the same canonical fingerprint;
6. re-checks that the newest locally captured state is still that successful state;
7. requires a newer Core acknowledgement with the same fingerprint.

The bounded history prevents a fast ACK from being lost between polling iterations without retaining many complete UI trees.

## Evidence-session behavior across reconnect

Core currently keeps live observation state in process memory. After a Core restart or a new registered WebSocket session, relying on an ACK from the previous connection would be unsafe.

The Android publisher therefore:

- invalidates executable acknowledged evidence when the connection is lost;
- also invalidates it immediately when an outbound send detects transport failure;
- clears fingerprint deduplication for a newly registered connection;
- automatically re-enqueues the most recent projected snapshot;
- preserves an in-flight envelope exactly when its ACK may merely have been lost.

This ensures a connected Core receives usable current state even when the visible screen did not change during the restart.

## Result mapping

| Condition | Outcome | Failure code | Attempts |
|---|---|---|---:|
| Desired state already exists | `succeeded` | `none` | 0 |
| Launch and verified visible state | `succeeded` | `none` | 1 |
| Expired command | `blocked` | `expired` | 0 |
| Stale or mismatched precondition | `blocked` | `precondition_failed` | 0 |
| Fresh pre-capture unavailable | `blocked` | `observation_timeout` | 0 |
| Background launch prerequisite absent | `blocked` | `unsupported_capability` | 0 |
| Package or front door missing | `failed` | `target_not_found` | 0 |
| URI invalid | `blocked` | `invalid_command` | 0 |
| Android rejects request | `failed` | `action_rejected` | 0 |
| Predicates false after launch | `failed` | `postcondition_failed` | 1 |
| Predicate resolution ambiguous | `blocked` | `postcondition_failed` | 1 |
| No newer stable observation or ACK | `timed_out` | `observation_timeout` | 1 |
| Cancellation before launch | `cancelled` | `cancelled` | 0 |
| Cancellation after launch acceptance | `cancelled` | `cancelled` | 1 |
| Unexpected exception after launch acceptance | `blocked` | `internal_error` | 1 |

`attempts` counts accepted side-effect requests. A guard, lookup, or validation rejection before Activity-start acceptance does not increment it.

## Cancellation semantics

Cancellation is cooperative:

- before launch, it returns a zero-attempt cancelled result;
- while waiting for fresh evidence, it stops waiting;
- after Android accepts the launch, it cannot roll the target transition back;
- the result records `attempts=1` when cancellation arrives after acceptance.

## Crash and replay semantics

The action command is committed to the encrypted Android write-ahead ledger before handler submission. If the process dies while execution is uncertain, the command is not run again. Recovery emits a conservative blocked result through the stable result-delivery channel.

The result publisher preserves message ID, correlation ID, payload, and original send timestamp across retries and reconstruction.

See:

- [`ANDROID_ACTION_TRANSPORT.md`](ANDROID_ACTION_TRANSPORT.md)
- ADR 0006: [`adr/0006-idempotent-android-action-delivery.md`](adr/0006-idempotent-android-action-delivery.md)
- ADR 0007: [`adr/0007-verified-android-open-app-execution.md`](adr/0007-verified-android-open-app-execution.md)

## Concurrency boundaries

- Core enforces one non-terminal action per device.
- Android's encrypted ledger enforces one recoverable action.
- `OpenAppActionExecutor` has an atomic single-flight guard.
- Execution and evidence waiting run on a dedicated single-thread executor.
- Accessibility callbacks publish immutable snapshots and never perform network planning.
- WebSocket writes are serialized.
- Result completion is delivered exactly once to the action router.

## Automated evidence

The JVM and Core test suite covers:

- successful verified launch;
- stale precondition rejection;
- TOCTOU fingerprint mismatch;
- already-satisfied zero-attempt success;
- missing background launch capability;
- missing target package;
- missing post-launch evidence;
- non-`open_app` rejection;
- cancellation before and after launch acceptance;
- explicit capture requiring a newer snapshot;
- stable samples plus matching newer ACK;
- a newer failing snapshot preventing success from an older ACK;
- stale ACK exclusion;
- compact self-state projection;
- live root identity overriding stale event hints;
- observation invalidation and state resubmission after reconnect;
- complete Core-to-Android command contract round trip.

CI builds the debug APK, runs Android JVM tests, and runs Android lint against stable API 36 with `minSdk=24`.

## Galaxy A53 physical validation protocol

Physical validation is not complete until the following are recorded:

1. exact model number;
2. Android version;
3. One UI version;
4. security patch date;
5. APK commit SHA;
6. target package and app version;
7. Accessibility connected state;
8. overlay special-access state;
9. before stream, sequence, snapshot ID, fingerprint, and active package;
10. command ID, action ID, and command-envelope ID;
11. selected launch adapter;
12. Android return or exception;
13. first post-launch local snapshot;
14. stable sample count;
15. matching Core acknowledgement;
16. typed result and result ACK;
17. foreground launch;
18. background launch;
19. lock-screen behavior;
20. battery-optimized mode;
21. unrestricted battery mode;
22. reconnect during verification;
23. Core restart while the screen is unchanged;
24. forced process death after launch acceptance.

Initial deterministic targets:

- Android Settings: `com.android.settings`;
- Calculator, if installed;
- Simorgh itself, using the package-only self projection;
- a dedicated fixture app with a stable front-door Activity.

Social applications are not the first validation targets because onboarding dialogs, account state, remote experiments, and OEM permission prompts make their initial UI less deterministic.

## Current boundary

This increment enables only `open_app`. It does not enumerate app content, click controls, type text, scroll, dispatch arbitrary gestures, or invoke global Accessibility actions.

The next side-effect increment is semantic `click_node`, contingent on:

- reacquiring a live node from a fresh tree;
- deterministic selector resolution;
- package, visibility, enabled-state, and action-capability checks;
- ancestor-click policy;
- optional coordinate fallback as a separately controlled mode;
- newer post-action evidence;
- fixture-app tests and Galaxy A53 validation.
