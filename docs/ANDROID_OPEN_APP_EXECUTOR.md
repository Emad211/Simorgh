# Verified Android `open_app` executor

Status: first live Android side-effect vertical slice

## Purpose

`open_app` opens one installed Android application's front-door activity, or one explicit package-scoped URI, and then proves the declared visible postconditions from fresh Accessibility evidence.

The implementation is intentionally narrow. Only `OpenAppOperation` owns a side-effect path in this increment. Click, text entry, scrolling, arbitrary gestures, and global Accessibility actions remain rejected until each receives an independent implementation, threat analysis, deterministic fixture, and physical-device validation.

## Non-negotiable invariants

1. Raw natural language never reaches Android execution code.
2. Core rejects semantically unsafe commands before broker ownership.
3. Android validates the typed command again after transport decoding.
4. `open_app(package_name)` must include `active_package_equals(package_name)` in verification.
5. At most one non-terminal device action exists per device.
6. No launch runs from state that Core has not acknowledged.
7. A newly captured local state must still match the acknowledged pre-action state.
8. Core evidence is read and validated again immediately before the launch boundary.
9. Android API acceptance is not success.
10. Success requires stable visible postconditions and a matching newer Core acknowledgement.
11. Core independently validates a successful result against the original command and its latest observation.
12. A newly captured failing state cannot be skipped during final verification.
13. An uncertain action after process death is never blindly replayed.
14. Every result carries typed outcome, failure code, attempt count, evidence references, and predicate evidence.

## End-to-end flow

```text
Core operator API
      |
      v
Core command semantic validation
      |
      v
typed AndroidActionCommand
      |
      v
device.action_command
      |
      v
Android contract + semantic validation
      |
      v
encrypted write-ahead ledger commit
      |
      v
initial Core-acknowledged observation
      |
      v
explicit fresh local capture
      |
      +---- fingerprint mismatch ----------------> BLOCKED
      |
      v
re-read current Core acknowledgement
      |
      +---- invalidated or changed --------------> BLOCKED
      |
      v
postconditions already true?
      |
      +---- yes ---------------------------------> SUCCEEDED, attempts=0
      |
      v
version-aware Android launch adapter
      |
      v
new projected Accessibility samples
      |
      v
stable typed postconditions
      |
      v
latest local state still satisfies?
      |
      v
matching newer Core acknowledgement
      |
      v
typed ActionResult
      |
      v
Core result semantic validation
      |
      +---- evidence mismatch -------------------> REJECTED ACK
      |
      v
durable result delivery acknowledgement
```

## Typed operation and mandatory package proof

```json
{
  "operation": {
    "kind": "open_app",
    "package_name": "com.example.app",
    "uri": "example://optional/path"
  },
  "verification": {
    "predicates": [
      {
        "kind": "active_package_equals",
        "package_name": "com.example.app"
      }
    ]
  }
}
```

Rules:

- `package_name` is mandatory;
- `uri` is optional;
- an explicit URI remains package-scoped with `Intent.setPackage`;
- verification must contain at least one `active_package_equals` predicate;
- every active-package predicate must equal the operation's `package_name`;
- additional node or state predicates are allowed;
- all other operation discriminators are rejected by the installed handler;
- at most one launch request is accepted per command.

The package proof is enforced twice:

1. Core's dispatch semantic validator rejects the command before broker ownership;
2. Android's contract validator rejects it after transport decoding.

This prevents an unrelated predicate from making `open_app(com.target)` appear already satisfied while another app is active.

## Package visibility model

Simorgh does **not** request `QUERY_ALL_PACKAGES` for this vertical slice.

Android 11 and newer filter many `PackageManager` query results. The API 24–32 launch path calls `PackageManager.getLaunchIntentForPackage`, whose documented front-door search order is:

1. `ACTION_MAIN` with `CATEGORY_INFO`;
2. `ACTION_MAIN` with `CATEGORY_LAUNCHER`.

The manifest therefore declares exactly those two intent signatures:

```xml
<queries>
    <intent>
        <action android:name="android.intent.action.MAIN" />
        <category android:name="android.intent.category.INFO" />
    </intent>
    <intent>
        <action android:name="android.intent.action.MAIN" />
        <category android:name="android.intent.category.LAUNCHER" />
    </intent>
</queries>
```

Consequences:

- API 24–29 already expose installed packages to this target without Android 11 filtering;
- API 30–32 can resolve launchable front-door activities without visibility over unrelated packages;
- API 33+ uses `getLaunchIntentSenderForPackage`, which Android documents as not restricted by package visibility;
- explicit URI launches call `startActivity()` directly and handle `ActivityNotFoundException`; Android does not require package visibility merely to start another app's Activity;
- the app does not enumerate or upload the installed-application inventory in this increment.

Official references:

- <https://developer.android.com/training/package-visibility/declaring>
- <https://developer.android.com/training/package-visibility/use-cases>
- <https://developer.android.com/reference/android/content/pm/PackageManager#getLaunchIntentForPackage(java.lang.String)>
- <https://developer.android.com/reference/android/content/pm/PackageManager#getLaunchIntentSenderForPackage(java.lang.String)>

## Background Activity launch policy

Android launch restrictions differ by platform generation. Simorgh uses a pure, JVM-tested policy rather than scattering assumptions through the executor.

| Android | API | Background launch prerequisite |
|---|---:|---|
| Android 7–9 | 24–28 | no overlay prerequisite in Simorgh's compatibility policy |
| Android 10+ | 29+ | Simorgh Activity visible **or** overlay special access granted |

For API 29 and newer:

```text
SimorghAppVisibility.isVisible()
        OR
Settings.canDrawOverlays(context)
```

If neither condition holds, no launch API is invoked:

```text
outcome = blocked
failure_code = unsupported_capability
attempts = 0
```

The launch guard is checked when the adapter is entered and again immediately before the platform side effect. Losing visibility between lookup and launch therefore fails closed.

The Persian UI reports one of three states:

- legacy Android: no special access required;
- modern Android: special access active;
- modern Android: special access missing.

The settings launcher tries, in order:

1. app-specific overlay settings;
2. general overlay settings;
3. general Android settings.

Expected OEM `ActivityNotFoundException` and `SecurityException` failures fall through to the next candidate. The UI does not crash when a vendor omits one settings Activity.

The overlay permission is a launch prerequisite only. It never proves the target became visible.

Official references:

- <https://developer.android.com/guide/components/activities/secure-bal>
- <https://developer.android.com/reference/android/provider/Settings#canDrawOverlays(android.content.Context)>

## Version-aware launch adapters

### Android 7–12 / API 24–32

```kotlin
PackageManager.getLaunchIntentForPackage(packageName)
```

The explicit front-door Intent receives:

```text
FLAG_ACTIVITY_NEW_TASK
FLAG_ACTIVITY_RESET_TASK_IF_NEEDED
```

A null result maps to `target_not_found` with `attempts=0`.

### Android 13+ / API 33+

```kotlin
PackageManager.getLaunchIntentSenderForPackage(packageName)
Context.startIntentSender(..., ActivityOptions)
```

The API 33 adapter is isolated behind `@RequiresApi(33)`. Android 7–12 never resolve that code path.

Missing-target paths are mapped consistently:

- `PackageManager.NameNotFoundException` while obtaining the sender;
- `IntentSender.SendIntentException` while invoking it.

Both become:

```text
outcome = failed
failure_code = target_not_found
attempts = 0
```

### IntentSender grant modes

The sender-side opt-in is selected by a pure policy and applied behind explicit API guards:

| API | Mode |
|---:|---|
| 33 | legacy `setPendingIntentBackgroundActivityLaunchAllowed(true)` |
| 34–35 | `MODE_BACKGROUND_ACTIVITY_START_ALLOWED` |
| 36+ and Simorgh visible | `MODE_BACKGROUND_ACTIVITY_START_ALLOW_IF_VISIBLE` |
| 36+ and Simorgh background with overlay | `MODE_BACKGROUND_ACTIVITY_START_ALLOW_ALWAYS` |

Android 16 split the earlier single `ALLOWED` mode into visible-only and always-allow variants. Simorgh chooses the narrower visible-only mode when possible and uses always-allow only for the private, explicitly configured background case.

The mode does not bypass Android policy. It expresses the required sender opt-in when a platform exception already applies.

Official references:

- <https://developer.android.com/reference/android/content/pm/PackageManager#getLaunchIntentSenderForPackage(java.lang.String)>
- <https://developer.android.com/reference/android/content/Context#startIntentSender(android.content.IntentSender,android.content.Intent,int,int,int,android.os.Bundle)>
- <https://developer.android.com/reference/android/app/ActivityOptions>

### Explicit package-scoped URI

```kotlin
Intent(Intent.ACTION_VIEW, uri)
    .setPackage(packageName)
    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
```

A URI requires a non-empty scheme. `ActivityNotFoundException` maps to `target_not_found`; `SecurityException` maps to `action_rejected`. A normal API return still requires visible postcondition evidence.

## Observation identity and root precedence

Accessibility events provide package and window hints. An explicit capture can occur before the newest event metadata arrives, so a target-app root could otherwise be mislabeled with the preceding app.

When `rootInActiveWindow` exists:

- the root node package is the active-package source of truth;
- the root node window ID is the active-window source of truth;
- event values are fallback hints only.

This behavior has a deterministic JVM test with deliberately stale event hints.

## Minimal Simorgh self-state projection

Simorgh must prove transitions both away from and into its own Activity. Sending the complete internal UI would expose connection fields and could create an observation/status feedback loop. Completely excluding self-snapshots would make transitions into Simorgh unverifiable.

The transport therefore projects a Simorgh snapshot to package presence only:

```text
active_package = ai.simorgh.android
active_window_id = null
root_node_id = null
windows = []
nodes = []
```

Capture identity and time remain intact. Internal text, endpoint fields, tokens, controls, windows, and nodes are removed. Different Simorgh screens produce the same canonical state fingerprint.

The same projection function is used by observation transport, local pre-launch evidence, and local post-launch evidence.

See ADR 0008: [`adr/0008-minimal-simorgh-self-state-observation.md`](adr/0008-minimal-simorgh-self-state-observation.md).

## Compact acknowledged evidence

An `AcknowledgedAccessibilityObservation` stores only:

- stream ID;
- sequence;
- canonical fingerprint;
- snapshot ID;
- capture timestamp;
- active package;
- Core acknowledgement timestamp.

It does not retain a second copy of the full UI tree. The bounded local history owns recent full projected snapshots; the acknowledgement history owns compact references.

## Initial preconditions

A command may bind to:

- exact stream ID;
- minimum sequence;
- exact state fingerprint;
- expected active package;
- maximum observation age.

The initial Core acknowledgement must satisfy every declared field. Any mismatch blocks before fresh capture or launch.

The default age budget is intentionally strict. Issue [#21](https://github.com/Emad211/Simorgh/issues/21) tracks an explicit fresh-observation handshake for unchanged screens. The implementation must not weaken freshness by silently enlarging `maximum_age_ms`.

## Fresh capture and TOCTOU protection

After command acceptance, the executor requests an immediate capture from the system Accessibility service. The returned projected snapshot must have:

- a new snapshot ID;
- `captured_at_ms` at or after the request;
- the same canonical fingerprint as the initial Core-acknowledged state.

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

## Launch-boundary evidence revalidation

The Core connection can fail after fresh capture but before the Android Activity-start call. Retaining only the local variable from the initial check would permit a launch based on evidence from an invalidated Core session.

Immediately before evaluating the already-satisfied state or launching, the executor:

1. reads the current acknowledgement again;
2. requires that it still exists;
3. validates every command precondition again;
4. requires its fingerprint to match the fresh local state;
5. checks cancellation again.

A disconnect or Core-session replacement at this boundary returns `blocked / precondition_failed / attempts=0`. The launcher is not called.

## Idempotent already-satisfied behavior

After launch-boundary revalidation, the complete verification policy is evaluated on the fresh local state.

If all predicates already hold:

```text
outcome = succeeded
failure_code = none
attempts = 0
before_observation = current Core acknowledgement
after_observation = same acknowledgement
```

Because target-package proof is mandatory, zero-attempt success also proves that the requested package is already active.

## Post-action evidence

The evidence source maintains bounded process-local history:

- latest 32 projected local snapshots;
- latest 64 compact Core acknowledgements.

After Android accepts the launch, it:

1. requests captures periodically;
2. ignores the pre-action snapshot;
3. ignores captures older than launch acceptance;
4. evaluates every typed predicate;
5. requires `stable_samples` consecutive satisfying snapshots with one fingerprint;
6. under the evidence monitor, re-checks that the newest local snapshot is processed, has that fingerprint, and still satisfies all predicates;
7. requires a newer Core acknowledgement with the same fingerprint.

Step 6 closes a race where a newer failing snapshot could arrive between a history copy and the success return.

## Core result verification

Android's result is a claim until Core verifies it.

For a successful `open_app`, Core requires:

- the result's command and action IDs to match the original dispatch;
- `attempts` to be either `0` or `1`;
- before and after observation references;
- `after_observation.active_package` to equal the target package;
- predicate evidence count and order to match the command policy;
- every predicate outcome to be `satisfied`;
- an `active_package_equals` proof for the target package;
- the after reference to match Core's latest observation exactly by stream, sequence, snapshot ID, fingerprint, capture time, and active package.

Additional ordering rules:

- zero-attempt success must use the same before and after observation;
- one-attempt success must use a strictly newer after observation within the same stream, or a different valid stream after a session transition;
- a result whose correlation ID does not match the original command envelope is rejected;
- a semantically invalid result receives `device.action_result_ack(status=rejected)` and is not recorded as terminal success.

Android keeps a rejected result in its encrypted ledger and blocks later actions. This fail-closed behavior avoids silently accepting an unverifiable side effect. Durable repair across a Core restart is tracked in issue [#22](https://github.com/Emad211/Simorgh/issues/22).

## Evidence-session behavior across reconnect

Core's current live-observation registry is process-local. An acknowledgement from a previous connection cannot remain executable evidence after disconnect or Core restart.

The Android publisher therefore:

- invalidates acknowledged evidence on connection loss;
- invalidates it immediately when a socket send fails;
- preserves acknowledgement subscribers during invalidation;
- serializes `publish` and `reset` delivery order;
- clears fingerprint deduplication for a new registered connection;
- re-enqueues the most recent projected snapshot even when the screen did not change;
- preserves an in-flight envelope exactly when an ACK may merely have been lost.

This restores usable current state after reconnect without continuously resending unchanged UI trees.

## Time model limitation

Absolute command deadlines and capture timestamps currently depend on Core and device wall clocks. Clock normalization, bounded uncertainty, and monotonic deadline accounting are tracked in issue [#23](https://github.com/Emad211/Simorgh/issues/23).

Until that issue is implemented, physical validation must record automatic-time state and measured clock skew.

## Result mapping

| Condition | Outcome | Failure code | Attempts |
|---|---|---|---:|
| Desired state already exists | `succeeded` | `none` | 0 |
| Launch and verified visible state | `succeeded` | `none` | 1 |
| Missing/conflicting package proof | rejected before dispatch | invalid-command semantics | 0 |
| Expired command | `blocked` | `expired` | 0 |
| Stale or mismatched precondition | `blocked` | `precondition_failed` | 0 |
| ACK invalidated at launch boundary | `blocked` | `precondition_failed` | 0 |
| Fresh pre-capture unavailable | `blocked` | `observation_timeout` | 0 |
| Modern background prerequisite absent | `blocked` | `unsupported_capability` | 0 |
| Package or front door missing | `failed` | `target_not_found` | 0 |
| URI invalid | `blocked` | `invalid_command` | 0 |
| Android rejects request | `failed` | `action_rejected` | 0 |
| Predicates false after launch | `failed` | `postcondition_failed` | 1 |
| Predicate resolution ambiguous | `blocked` | `postcondition_failed` | 1 |
| No newer stable observation or ACK | `timed_out` | `observation_timeout` | 1 |
| Cancellation before launch | `cancelled` | `cancelled` | 0 |
| Cancellation after launch acceptance | `cancelled` | `cancelled` | 1 |
| Unexpected exception after launch acceptance | `blocked` | `internal_error` | 1 |
| Core cannot prove a claimed success | result ACK `rejected` | not stored as terminal success | unchanged |

`attempts` counts accepted side-effect requests. Guards, lookups, validation failures, and missing-target exceptions before Activity-start acceptance do not increment it.

## Cancellation semantics

Cancellation is cooperative:

- before launch, it returns a zero-attempt cancelled result;
- while waiting for fresh evidence, it stops waiting;
- after Android accepts the launch, it cannot roll back the target transition;
- the result records `attempts=1` when cancellation arrives after acceptance.

## Crash and replay semantics

The command is committed to the encrypted Android write-ahead ledger before handler submission. If the process dies while execution is uncertain, the command is not run again. Recovery emits a conservative blocked result through the stable result-delivery channel.

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
- Acknowledgement publication and invalidation are ordered.
- Result completion is delivered exactly once to the action router.

## Automated evidence

The JVM and Core suites cover:

- mandatory target-package proof in Core and Android;
- verified launch success;
- Core rejection of unproven success;
- stale precondition rejection;
- TOCTOU fingerprint mismatch;
- acknowledgement invalidation at the launch boundary;
- already-satisfied zero-attempt success;
- background launch policy for API 24, 28, 29, and 36;
- IntentSender grant modes for API 33, 34, 35, and 36;
- missing background launch capability;
- missing target package;
- missing post-launch evidence;
- non-`open_app` rejection;
- cancellation before and after launch acceptance;
- explicit capture requiring a newer snapshot;
- stable samples plus matching newer ACK;
- a newer failing snapshot preventing success from an older ACK;
- stale ACK exclusion;
- acknowledgement invalidation without subscription loss;
- compact self-state projection;
- live root identity overriding stale event hints;
- state resubmission after reconnect;
- complete Core-to-Android command contract round trip;
- Android ledger retention after a rejected result ACK.

CI builds the debug APK, runs Android JVM tests, and runs Android lint against stable API 36 with `minSdk=24`.

## Galaxy A53 physical validation protocol

Physical validation is not complete until the following are recorded:

1. exact model number;
2. Android version;
3. One UI version;
4. security patch date;
5. automatic date/time setting and measured Core/device skew;
6. APK commit SHA;
7. target package and app version;
8. Accessibility connected state;
9. overlay special-access state;
10. before stream, sequence, snapshot ID, fingerprint, and active package;
11. command ID, action ID, and command-envelope ID;
12. selected launch adapter;
13. selected IntentSender grant mode, when applicable;
14. Android return or exception;
15. first post-launch local snapshot;
16. stable sample count;
17. matching Core acknowledgement;
18. typed result and result ACK;
19. foreground launch;
20. background launch;
21. lock-screen behavior;
22. battery-optimized mode;
23. unrestricted battery mode;
24. reconnect during verification;
25. Core restart while the screen is unchanged;
26. forced process death after launch acceptance.

Initial deterministic targets:

- Android Settings: `com.android.settings`;
- Calculator, if installed;
- Simorgh itself, using package-only self projection;
- a dedicated fixture app with a stable front-door Activity.

Social applications are not first validation targets because onboarding dialogs, account state, remote experiments, and OEM permission prompts make their initial UI less deterministic.

## Current boundary

This increment enables only `open_app`. It does not enumerate app content, click controls, type text, scroll, dispatch arbitrary gestures, or invoke global Accessibility actions.

The next side-effect increment is semantic `click_node`, contingent on:

- reacquiring a live node from a fresh tree;
- deterministic selector resolution;
- package, visibility, enabled-state, and action-capability checks;
- ancestor-click policy;
- coordinate fallback as an independently controlled mode;
- newer post-action evidence;
- fixture-app tests and Galaxy A53 validation.
