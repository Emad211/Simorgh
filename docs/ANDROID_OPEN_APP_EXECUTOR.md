# Verified Android `open_app` executor

Status: first live Android side-effect vertical slice

## Purpose

`open_app` launches one installed Android application's front-door activity or one explicit package-scoped URI, then proves the declared visible postconditions from fresh Accessibility evidence.

It is intentionally narrower than a general mobile agent. The executor accepts only the typed `OpenAppOperation`; click, text entry, scroll, gestures, and global actions remain rejected until their own implementations and evidence are reviewed.

## Success definition

Android accepting `startActivity` or `startIntentSender` is not success. The operation succeeds only when:

1. the command is valid and unexpired;
2. a recent Accessibility observation acknowledged by Core satisfies the command precondition;
3. a newly captured local snapshot has the same canonical state fingerprint, preventing a time-of-check/time-of-use race;
4. Android accepts the launch request, unless the desired state already exists;
5. one or more newer local snapshots satisfy every typed postcondition;
6. a newer observation with the same state fingerprint is acknowledged by Core;
7. the final typed result contains before/after evidence and predicate outcomes.

```text
Core-ACKed observation
        |
        v
fresh local capture ---- fingerprint differs ----> BLOCKED
        |
        v
postconditions already true? ---- yes ----> SUCCEEDED, attempts=0
        |
        no
        v
launch adapter request
        |
        v
stable local postcondition samples
        |
        v
matching newer Core ACK
        |
        v
SUCCEEDED
```

## Android background activity launch constraint

Starting an application is an Activity launch. A Foreground Service does not by itself permit arbitrary background Activity starts. Android's Activity Security documentation states that background launches are allowed when the app has a visible window or the user has granted `SYSTEM_ALERT_WINDOW`, among other system-specific exceptions.

Official reference:

- <https://developer.android.com/guide/components/activities/secure-bal>

Simorgh therefore performs an explicit local guard:

```text
Simorgh Activity visible
        OR
Settings.canDrawOverlays(context) == true
```

If neither condition is true, the command returns:

```text
outcome = blocked
failure_code = unsupported_capability
attempts = 0
```

No launch request is issued. The Android UI contains a Persian setup card that opens the system **Display over other apps** special-access screen.

This is a technical runtime prerequisite for the private always-on operator. It does not replace postcondition verification: OEMs can still suppress or alter a launch, so the visible result is always observed.

## Manifest and package discovery

The private operator declares:

```xml
<uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW" />
<uses-permission android:name="android.permission.QUERY_ALL_PACKAGES" />
```

`QUERY_ALL_PACKAGES` is used because this private app is designed to discover and open arbitrary installed applications. The executable does not enumerate or upload installed packages in this increment; the permission supports deterministic front-door resolution on older Android releases.

## Launch adapters

### Android 7–12 / API 24–32

The executor uses:

```kotlin
PackageManager.getLaunchIntentForPackage(packageName)
```

The returned explicit front-door Intent receives:

- `FLAG_ACTIVITY_NEW_TASK`;
- `FLAG_ACTIVITY_RESET_TASK_IF_NEEDED`.

A null result is `target_not_found`.

### Android 13+ / API 33+

The executor uses:

```kotlin
PackageManager.getLaunchIntentSenderForPackage(packageName)
```

Android documents this API as not restricted by package visibility. Simorgh launches it through:

```kotlin
Context.startIntentSender(..., activityOptions)
```

Official references:

- <https://developer.android.com/reference/android/content/pm/PackageManager#getLaunchIntentSenderForPackage(java.lang.String)>
- <https://developer.android.com/reference/android/content/Context#startIntentSender(android.content.IntentSender,android.content.Intent,int,int,int,android.os.Bundle)>

For Android 13, the legacy sender-side background-launch opt-in is supplied through `ActivityOptions`. For Android 14+, the explicit `MODE_BACKGROUND_ACTIVITY_START_ALLOWED` mode is supplied. These options do not bypass platform policy; they express the required sender opt-in when an allowed BAL exception exists.

### Explicit package-scoped URI

When `operation.uri` is present, Simorgh creates:

```kotlin
Intent(Intent.ACTION_VIEW, uri)
    .setPackage(packageName)
    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
```

Rules:

- URI must contain a non-empty scheme;
- resolution remains restricted to the requested package;
- `ActivityNotFoundException` is `target_not_found`;
- `SecurityException` is `action_rejected`;
- success still requires the command's UI postconditions.

## Self-launch guard

Simorgh filters its own package from observation transport and the local inspector. It therefore refuses `open_app` targeting `ai.simorgh.android` because the result would not be independently observable through the current evidence pipeline.

```text
outcome = failed
failure_code = action_rejected
adapter = self_package_guard
```

A future self-navigation mechanism must use an explicit internal contract rather than pretending it is an external app operation.

## Precondition evidence

The executor requires a non-stale `AcknowledgedAccessibilityObservation` containing:

- observation stream ID;
- sequence;
- canonical state fingerprint;
- immutable snapshot;
- Core acknowledgement timestamp.

The command can bind to:

- exact stream ID;
- minimum sequence;
- exact state fingerprint;
- expected active package;
- maximum observation age.

Failure of any declared condition returns `precondition_failed` with `attempts=0`.

## Explicit fresh capture and TOCTOU protection

The system Accessibility service exposes a process-local capture request boundary. The executor requests a snapshot after the command is accepted and requires:

- a new snapshot ID;
- `captured_at_ms` at or after the request time;
- canonical fingerprint equal to the last Core-acknowledged fingerprint.

A different fingerprint means the screen changed between planning and execution. The executor blocks rather than launching from stale context.

The command's pre-launch capture budget is the smaller of:

- 2,000 ms;
- remaining command deadline.

## Idempotent already-satisfied behavior

After the fresh snapshot passes the fingerprint guard, the executor evaluates the complete verification policy before launching.

If every predicate is already satisfied:

```text
outcome = succeeded
failure_code = none
attempts = 0
before_observation = latest Core-ACKed observation
after_observation = same Core-ACKed observation
```

This is valid because the fresh local snapshot has the same canonical fingerprint as the acknowledged observation. It prevents unnecessary task switching when the requested app or deep-link destination is already in the declared desired state.

## Post-action evidence

`AccessibilityActionEvidenceSource` keeps bounded process-local histories of:

- the latest 64 local Accessibility snapshots;
- the latest 64 Core-acknowledged observations.

The history prevents a fast acknowledgement from being lost between polling iterations.

After Android accepts the launch, the evidence source:

1. requests fresh captures periodically;
2. ignores the pre-action snapshot;
3. ignores snapshots captured before launch;
4. evaluates the typed verification policy;
5. requires `stable_samples` consecutive satisfying snapshots with the same canonical fingerprint;
6. requires a newer Core acknowledgement with that fingerprint.

Only this combined evidence can produce `succeeded`.

## Result mapping

| Condition | Outcome | Failure code | Attempts |
|---|---|---|---:|
| Desired state already exists | `succeeded` | `none` | 0 |
| Launch and verified state | `succeeded` | `none` | 1 |
| Stale/mismatched precondition | `blocked` | `precondition_failed` | 0 |
| Fresh pre-capture unavailable | `blocked` | `observation_timeout` | 0 |
| Background launch access absent | `blocked` | `unsupported_capability` | 0 |
| Package/front door not found | `failed` | `target_not_found` | 0 |
| URI invalid | `blocked` | `invalid_command` | 0 |
| Android rejects request | `failed` | `action_rejected` | 0 |
| Predicates false after launch | `failed` | `postcondition_failed` | 1 |
| Predicate resolution ambiguous | `blocked` | `postcondition_failed` | 1 |
| No newer observation/ACK | `timed_out` | `observation_timeout` | 1 |
| Cancellation before launch | `cancelled` | `cancelled` | 0 |
| Cancellation after launch acceptance | `cancelled` | `cancelled` | 1 |
| Unexpected exception after launch acceptance | `blocked` | `internal_error` | 1 |

The `attempts` field counts accepted side-effect attempts. Adapter rejection before an Activity start is not counted as an executed side effect.

## Cancellation semantics

Cancellation is cooperative:

- before launch, it returns a zero-attempt cancelled result;
- while waiting for post-action evidence, it stops waiting and returns cancelled;
- after Android accepted the launch, it cannot roll back the target app transition;
- the result explicitly records `attempts=1` when cancellation arrived after acceptance.

## Concurrency

- one active device action is enforced by Core and the Android encrypted ledger;
- `OpenAppActionExecutor` has its own atomic single-flight guard;
- execution and evidence waiting run on a dedicated single-thread executor;
- Accessibility callbacks only publish snapshots and never block on network or planning;
- result completion is invoked exactly once through the guarded handler registry.

## Failure containment

- raw natural language never reaches the launcher;
- unknown operation kinds are rejected by the handler;
- self-launch is rejected;
- no launch occurs from a stale or unacknowledged state;
- no successful result is produced from an Android API return alone;
- process death after an uncertain side effect is handled by the encrypted transport ledger and is never blindly replayed;
- unknown or malformed protocol messages fail closed in the WebSocket layer.

## Test strategy

### Pure JVM state-machine tests

- successful launch requires fresh precondition and newer Core-ACKed postcondition;
- stale observation blocks before launch;
- TOCTOU fingerprint mismatch blocks before launch;
- already-satisfied desired state skips launch with `attempts=0`;
- missing background-launch access maps to `unsupported_capability`;
- missing target maps to `target_not_found`;
- accepted launch without post evidence times out;
- non-`open_app` operation is rejected;
- fresh capture waits for a new snapshot;
- stable samples require a matching newer Core ACK;
- stale observation acknowledgements never become executable evidence;
- accepted acknowledgements publish the exact immutable snapshot.

### CI Android compatibility

The production lane builds and lints against stable API 36 with `minSdk=24`. SDK guards cover API 33 and API 34 launch additions; the API 24 path contains no unguarded newer calls.

### Galaxy A53 physical protocol

Record all of the following before declaring physical validation complete:

1. exact model number, Android version, One UI version, and security patch;
2. Simorgh APK commit SHA;
3. target application package and version;
4. Accessibility observer connected state;
5. overlay special-access state;
6. before observation stream, sequence, snapshot ID, fingerprint, and active package;
7. command, action, and command-envelope IDs;
8. selected launch adapter;
9. Android launch return or exception;
10. first post-launch local snapshot;
11. stable sample count;
12. matching Core acknowledgement;
13. typed result and result ACK;
14. foreground and background launch variants;
15. lock-screen behavior;
16. battery-optimized and unrestricted battery modes;
17. reconnect during postcondition waiting;
18. forced process death after launch acceptance to verify no replay.

Suggested deterministic targets:

- Android Settings (`com.android.settings`);
- Calculator, if installed;
- a dedicated Simorgh fixture app with a stable package and front-door activity.

Social-media apps are not first evidence targets because onboarding dialogs, account state, OEM permissions, and remote experiments make their launch UI less deterministic.

## Current boundary

This increment enables only `open_app`. It does not enumerate app content, click controls, type text, scroll, dispatch arbitrary gestures, or invoke global actions.

The next side-effect increment should implement semantic `click_node` only after:

- live node reacquisition from a fresh tree;
- deterministic selector resolution;
- `ACTION_CLICK` capability verification;
- optional coordinate fallback policy;
- newer post-action evidence;
- deterministic fixture-app and Galaxy A53 validation.
