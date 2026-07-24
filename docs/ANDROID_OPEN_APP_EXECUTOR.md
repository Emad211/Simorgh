# Verified Android `open_app` executor

Status: first live Android side-effect vertical slice

## 1. Purpose and boundary

`open_app` opens one installed Android application's front-door Activity or one explicit package-scoped URI and then proves the declared visible state from fresh Accessibility evidence.

Only `OpenAppOperation` owns a side-effect path in this increment. The installed handler still rejects:

- `click_node`;
- `set_text`;
- `scroll_node`;
- arbitrary gestures;
- global Accessibility actions.

Those operations require their own live-node reacquisition, selector policy, execution adapter, postcondition proof, deterministic fixture, and Samsung validation.

## 2. Non-negotiable invariants

1. Raw natural language never reaches Android execution code.
2. Core rejects semantically unsafe commands before broker ownership.
3. Android validates the typed command again after decoding it.
4. `open_app(package_name)` must prove the target package is active.
5. `open_app(package_name, uri)` must additionally prove a destination inside that package.
6. At most one non-terminal action exists per device.
7. Android commits the command to an encrypted write-ahead ledger before handler ownership.
8. No launch runs from UI state that Core has not acknowledged.
9. A fresh local capture must still match the acknowledged pre-action state.
10. Core evidence is re-read immediately before the launch boundary.
11. Background-launch eligibility is re-read immediately before the Android call.
12. Android API acceptance is never final success.
13. Success requires stable local postconditions and matching Core-acknowledged evidence.
14. A newer failing local state cannot be skipped while returning success.
15. Core independently validates successful Android results.
16. Exact observation replay cannot alter any payload metadata under the same message identity.
17. An uncertain action after process death is never blindly replayed.
18. Every result carries typed outcome, failure code, attempt count, observation references, and predicate evidence.

## 3. End-to-end state machine

```text
trusted operator request
        |
        v
Core schema validation
        |
        v
Core command semantic validation
        |
        v
typed AndroidActionCommand
        |
        v
device.action_command over authenticated WebSocket
        |
        v
Android schema + command semantic validation
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
        +---- projected fingerprint differs ----------> BLOCKED
        |
        v
re-read current Core acknowledgement
        |
        +---- missing, stale, or changed -------------> BLOCKED
        |
        v
front-door desired state already true?
        |
        +---- yes ------------------------------------> SUCCEEDED, attempts=0
        |
        v
version-aware launch adapter
        |
        v
new projected Accessibility samples
        |
        v
stable typed postconditions
        |
        v
newest local state still satisfies all predicates
        |
        v
matching newer Core acknowledgement
        |
        v
typed AndroidActionResult
        |
        v
Core result semantic validation against exact ACK history
        |
        +---- evidence mismatch ----------------------> REJECTED ACK
        |
        v
durable Android result-delivery acknowledgement
```

## 4. Typed front-door command

```json
{
  "operation": {
    "kind": "open_app",
    "package_name": "com.example.app"
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

Front-door rules:

- `package_name` is mandatory;
- at least one `active_package_equals` predicate is mandatory;
- every active-package predicate must equal `operation.package_name`;
- node predicates are optional, but any node selector must target the operation package;
- the handler allows at most one accepted launch request;
- zero-attempt success is permitted only when all postconditions already hold in fresh state matching current Core evidence.

## 5. Typed deep-link command

```json
{
  "operation": {
    "kind": "open_app",
    "package_name": "com.example.app",
    "uri": "example://items/42"
  },
  "verification": {
    "predicates": [
      {
        "kind": "active_package_equals",
        "package_name": "com.example.app"
      },
      {
        "kind": "node_exists",
        "selector": {
          "package_name": "com.example.app",
          "view_id": "com.example.app:id/item_42"
        }
      }
    ]
  }
}
```

A URI means navigation rather than simple application activation. Therefore:

- the URI requires a non-empty scheme;
- the Intent remains package-scoped through `Intent.setPackage`;
- target-package proof is mandatory;
- at least one node predicate targeting the same package is mandatory to prove the destination;
- node predicates targeting another package are rejected;
- zero-attempt success is forbidden;
- Android must issue one accepted URI launch attempt;
- Core rejects a successful URI result whose `attempts` is not exactly one.

This prevents a command from being marked successful merely because the app is already foregrounded on the wrong screen.

## 6. Semantic validation boundaries

The command is checked at two independent trust boundaries:

### Core

Before broker ownership, Core verifies:

- target-package proof exists;
- active-package predicates match the target;
- every node selector targets the target package;
- URI commands include destination proof.

### Android

After transport decoding, Android repeats the same cross-field checks. A malformed or semantically unsafe command never reaches the encrypted ledger's side-effect handler.

## 7. Narrow package visibility

Simorgh does **not** request `QUERY_ALL_PACKAGES` for this operation.

Android 11+ filters many `PackageManager` query results. The API 24–32 adapter calls `getLaunchIntentForPackage`, whose documented search order is:

1. `ACTION_MAIN` + `CATEGORY_INFO`;
2. `ACTION_MAIN` + `CATEGORY_LAUNCHER`.

The manifest declares exactly those signatures:

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

- API 24–29 do not apply Android 11 package-query filtering;
- API 30–32 can resolve launchable front doors without visibility over unrelated packages;
- API 33+ uses `getLaunchIntentSenderForPackage`, which Android documents as not restricted by package visibility;
- explicit URI launches call `startActivity` directly and map `ActivityNotFoundException` to a typed missing-target failure;
- the current increment does not enumerate or upload installed applications.

Official references:

- <https://developer.android.com/training/package-visibility/declaring>
- <https://developer.android.com/training/package-visibility/use-cases>
- <https://developer.android.com/reference/android/content/pm/PackageManager#getLaunchIntentForPackage(java.lang.String)>
- <https://developer.android.com/reference/android/content/pm/PackageManager#getLaunchIntentSenderForPackage(java.lang.String)>

## 8. Background Activity-launch policy

A Foreground Service is not unrestricted Activity-start authorization.

The compatibility policy is explicit and JVM-tested:

| Android | API | Simorgh prerequisite |
|---|---:|---|
| Android 7–9 | 24–28 | no overlay prerequisite imposed by Simorgh |
| Android 10+ | 29+ | Simorgh visible **or** overlay special access granted |

For API 29+:

```text
SimorghAppVisibility.isVisible()
        OR
Settings.canDrawOverlays(context)
```

If false:

```text
outcome = blocked
failure_code = unsupported_capability
attempts = 0
```

The eligibility guard runs twice:

1. before target resolution;
2. immediately before `startActivity` or `startIntentSender`.

Losing foreground visibility between those points cannot cross the side-effect boundary unless overlay access remains active.

The Persian setup UI reports whether the current platform requires this access and tries these settings surfaces in order:

1. app-specific overlay settings;
2. general overlay settings;
3. general Android settings.

Expected OEM `ActivityNotFoundException` and `SecurityException` errors fall through rather than crash the app.

Official references:

- <https://developer.android.com/guide/components/activities/secure-bal>
- <https://developer.android.com/reference/android/provider/Settings#canDrawOverlays(android.content.Context)>

## 9. Version-aware launch adapters

### API 24–32

```kotlin
PackageManager.getLaunchIntentForPackage(packageName)
```

The explicit front-door Intent receives:

```text
FLAG_ACTIVITY_NEW_TASK
FLAG_ACTIVITY_RESET_TASK_IF_NEEDED
```

A null Intent maps to:

```text
outcome = failed
failure_code = target_not_found
attempts = 0
```

### API 33+

```kotlin
PackageManager.getLaunchIntentSenderForPackage(packageName)
Context.startIntentSender(..., ActivityOptions)
```

The adapter is isolated behind `@RequiresApi(33)`, so Android 7–12 never resolve newer calls.

Missing-target paths:

- `PackageManager.NameNotFoundException` while obtaining the sender;
- `IntentSender.SendIntentException` while invoking it.

Both map to `target_not_found` with zero attempts.

### Sender-side background-start mode

| API | Mode |
|---:|---|
| 33 | legacy boolean opt-in |
| 34–35 | `MODE_BACKGROUND_ACTIVITY_START_ALLOWED` |
| 36+ and Simorgh visible | `MODE_BACKGROUND_ACTIVITY_START_ALLOW_IF_VISIBLE` |
| 36+ and Simorgh background with overlay | `MODE_BACKGROUND_ACTIVITY_START_ALLOW_ALWAYS` |

Android 16 split the previous broad mode. Simorgh selects the narrower visible-only mode whenever possible.

### Package-scoped URI

```kotlin
Intent(Intent.ACTION_VIEW, uri)
    .setPackage(packageName)
    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
```

Mapping:

- blank scheme: `invalid_command`;
- `ActivityNotFoundException`: `target_not_found`;
- `SecurityException`: `action_rejected`;
- normal return: one accepted attempt, still awaiting postcondition proof.

## 10. Accessibility root identity

Accessibility events contain package and window hints, but explicit capture can occur before the newest event metadata arrives.

When `rootInActiveWindow` exists:

- root package overrides event package;
- root window ID overrides event window ID;
- event values are fallback hints only.

A deterministic test deliberately supplies a stale event package and a live root from another package.

## 11. Minimal Simorgh self-state projection

The operator must prove transitions both away from and into Simorgh. Sending Simorgh's complete UI would expose connection fields and could create an observation/status feedback loop. Excluding every self-snapshot would make transitions into Simorgh unverifiable.

Self-state is projected to:

```text
active_package = ai.simorgh.android
active_window_id = null
root_node_id = null
windows = []
nodes = []
```

Capture identity and time remain. Internal text, endpoint fields, tokens, controls, windows, and nodes are removed. Different Simorgh screens produce one canonical package-presence state.

The same projection function is used by transport, pre-launch evidence, and post-launch evidence.

See ADR 0008: [`adr/0008-minimal-simorgh-self-state-observation.md`](adr/0008-minimal-simorgh-self-state-observation.md).

## 12. Initial Core-acknowledged precondition

A command can bind to:

- exact stream ID;
- minimum sequence;
- exact state fingerprint;
- expected active package;
- maximum observation age.

Android first requires a compact acknowledged reference satisfying every declared field.

The default age budget remains deliberately strict. Issue [#21](https://github.com/Emad211/Simorgh/issues/21) tracks an explicit refresh handshake for an unchanged screen. Simorgh must not weaken stale-state protection by silently enlarging `maximum_age_ms`.

## 13. Fresh local capture and TOCTOU protection

After accepting the command, Android requests an immediate capture from the system Accessibility service.

The projected snapshot must have:

- a new snapshot ID;
- capture time at or after the request;
- the same canonical state fingerprint as the acknowledged state.

Budget:

```text
min(2,000 ms, remaining command deadline)
```

A mismatch means the UI changed between planning and execution:

```text
outcome = blocked
failure_code = precondition_failed
attempts = 0
```

## 14. Launch-boundary Core-evidence revalidation

The Core connection can fail after fresh capture but before the Android launch call.

Immediately before idempotency evaluation or launch, Android:

1. reads the current acknowledgement again;
2. requires that it still exists;
3. validates all preconditions again;
4. requires its fingerprint to equal the fresh local fingerprint;
5. checks cancellation again.

A disconnect or session replacement at this boundary returns `blocked / precondition_failed / attempts=0` and does not call the launcher.

## 15. Already-satisfied behavior

Already-satisfied success exists only for front-door commands with `uri=null`.

If every declared predicate already holds in fresh local state matching the current Core acknowledgement:

```text
outcome = succeeded
failure_code = none
attempts = 0
before_observation = current acknowledgement
after_observation = same acknowledgement
```

Because target-package proof is mandatory, this proves the requested package is already active.

URI commands always execute one navigation attempt, even when the destination predicate appears to hold before launch. This prevents a stale or coincidentally matching screen from suppressing explicit navigation.

## 16. Android post-action evidence

Android keeps bounded process-local histories:

- 32 complete projected local snapshots;
- 64 compact Core acknowledgement references.

After platform launch acceptance, Android:

1. requests fresh captures periodically;
2. ignores the pre-action snapshot;
3. ignores captures older than launch acceptance;
4. evaluates every typed predicate;
5. requires `stable_samples` consecutive satisfying snapshots with one fingerprint;
6. under the evidence monitor, re-checks that the newest local snapshot is processed, has the successful fingerprint, and still satisfies every predicate;
7. requires a newer Core acknowledgement with the same fingerprint.

Step 6 closes the race where a newer failing snapshot arrives immediately before success returns.

## 17. Core acknowledged-observation history

Valid action-result messages can arrive after a newer observation because observation and result messages share an asynchronous network path.

Core therefore keeps up to 256 compact acknowledged observations per device. Each entry contains:

- observation message ID;
- Core session ID;
- Core receive time;
- stream ID;
- sequence;
- snapshot ID;
- state fingerprint;
- capture time;
- active package.

The key is the exact stream, sequence, snapshot ID, and fingerprint. The capacity is deliberately bounded. With the current normal minimum observation interval of 500 ms and maximum action lifetime of 120 seconds, no more than 240 normally rate-limited states fit in one command lifetime; 256 provides a small margin while bounding memory.

If a required reference has already been evicted, verification fails closed.

## 18. Exact replay integrity

Canonical UI fingerprint intentionally excludes capture identity and time so unchanged state deduplicates efficiently. That fingerprint is not sufficient to prove an exact message replay.

For each recent `message_id`, Core also stores SHA-256 over the complete normalized observation payload. Therefore the same message ID cannot alter:

- capture time;
- snapshot ID;
- stream or sequence;
- active package;
- tree content;
- any other payload field.

An exact replay refreshes both message and evidence LRU entries. A conflicting replay raises a typed observation conflict and does not replace evidence.

## 19. Core result trust boundary

An Android result is a claim until Core validates it against:

- the original command;
- exact acknowledged before evidence;
- exact acknowledged after evidence;
- the command's ordered verification policy.

For successful `open_app`, Core requires:

- command ID and action ID match;
- attempt count is zero or one;
- URI command attempt count is exactly one;
- before and after references exist in acknowledged history;
- `after.active_package` equals the target package;
- result Predicate Evidence has the same length and order as the command policy;
- every Predicate Evidence outcome is `satisfied`;
- `active_package_equals` Evidence contains no selector resolution;
- successful `node_exists`, `node_text_equals`, `node_checked_equals`, and `node_enabled_equals` Evidence has `resolution.outcome=resolved`, selected node ID, and selected path;
- successful `node_absent` Evidence has `resolution.outcome=not_found` and no selected node;
- zero-attempt front-door success uses identical before and after references;
- one-attempt success uses a newer after sequence within the same stream or valid newer evidence from another stream;
- Core acknowledgement order is not reversed;
- result correlation points to the original command envelope.

Failure response:

```text
device.action_result_ack
status = rejected
```

A rejected result is not stored as terminal success. Android keeps it in the encrypted ledger and blocks new actions instead of silently accepting an unverifiable side effect.

Durable repair across Core restart is tracked in issue [#22](https://github.com/Emad211/Simorgh/issues/22).

## 20. Evidence invalidation across reconnect

An acknowledgement from a previous Core connection is not executable evidence after disconnect or session replacement.

Android therefore:

- invalidates current acknowledged evidence on connection loss;
- invalidates it immediately when an outbound send detects transport failure;
- preserves acknowledgement subscribers during invalidation;
- serializes acknowledgement publication and reset ordering;
- clears fingerprint deduplication for a newly registered connection;
- resubmits the latest projected state even if the screen did not change;
- preserves an exact in-flight envelope when only its ACK may have been lost.

## 21. Time model limitation

Action deadlines and capture timestamps currently use Core and device wall clocks. Issue [#23](https://github.com/Emad211/Simorgh/issues/23) tracks:

- midpoint-based Core clock estimation;
- monotonic local durations;
- uncertainty bounds;
- wall-clock jump detection;
- fail-closed deadline handling under excessive uncertainty.

Until implemented, physical validation records automatic-time state and measured skew.

## 22. Result mapping

| Condition | Outcome | Failure code | Attempts |
|---|---|---|---:|
| Front-door desired state already exists | `succeeded` | `none` | 0 |
| Launch and verified visible state | `succeeded` | `none` | 1 |
| URI command lacks destination proof | rejected before dispatch | semantic invalid command | 0 |
| URI success reports zero attempts | result ACK `rejected` | not terminal | 0 |
| Expired command | `blocked` | `expired` | 0 |
| Initial stale/mismatched precondition | `blocked` | `precondition_failed` | 0 |
| ACK invalidated at launch boundary | `blocked` | `precondition_failed` | 0 |
| Fresh capture unavailable | `blocked` | `observation_timeout` | 0 |
| Modern background prerequisite absent | `blocked` | `unsupported_capability` | 0 |
| Package/front door missing | `failed` | `target_not_found` | 0 |
| URI scheme missing | `blocked` | `invalid_command` | 0 |
| Android rejects launch | `failed` | `action_rejected` | 0 |
| Predicates false after launch | `failed` | `postcondition_failed` | 1 |
| Predicate resolution ambiguous | `blocked` | `postcondition_failed` | 1 |
| No newer stable state/ACK | `timed_out` | `observation_timeout` | 1 |
| Cancellation before launch | `cancelled` | `cancelled` | 0 |
| Cancellation after launch acceptance | `cancelled` | `cancelled` | 1 |
| Unexpected exception after acceptance | `blocked` | `internal_error` | 1 |
| Core cannot prove claimed success | result ACK `rejected` | not terminal | unchanged |

`attempts` counts accepted side-effect requests. Guards, lookups, validation failures, and missing-target errors before platform acceptance do not increment it.

## 23. Cancellation semantics

Cancellation is cooperative:

- before launch: cancelled with zero attempts;
- while waiting for fresh evidence: stop waiting;
- after Android accepts launch: transition cannot be rolled back;
- after acceptance: result records one attempt.

## 24. Crash and replay semantics

Android commits the command to its encrypted write-ahead ledger before handler submission.

If process death makes execution uncertain:

- the command is not run again;
- recovery emits a conservative blocked result;
- result message ID, command correlation, payload, and original send time remain stable across retry.

See:

- [`ANDROID_ACTION_TRANSPORT.md`](ANDROID_ACTION_TRANSPORT.md)
- ADR 0006: [`adr/0006-idempotent-android-action-delivery.md`](adr/0006-idempotent-android-action-delivery.md)
- ADR 0007: [`adr/0007-verified-android-open-app-execution.md`](adr/0007-verified-android-open-app-execution.md)

## 25. Concurrency boundaries

- Core enforces one non-terminal action per device.
- Android ledger enforces one recoverable action.
- `OpenAppActionExecutor` has an atomic single-flight guard.
- execution and evidence waiting use one dedicated executor;
- Accessibility callbacks only publish immutable snapshots;
- WebSocket writes are serialized;
- acknowledgement publication/invalidation is ordered;
- result completion reaches the action router exactly once.

## 26. Automated evidence

Core and Android tests cover:

- target-package proof in Core and Android;
- URI destination proof in Core and Android;
- explicit URI always causing a launch attempt;
- zero-attempt URI success rejection;
- successful verified launch;
- already-satisfied front-door success;
- stale precondition rejection;
- TOCTOU fingerprint mismatch;
- acknowledgement invalidation at the launch boundary;
- background policy for API 24, 28, 29, and 36;
- sender modes for API 33, 34, 35, and 36;
- missing target and missing post-launch evidence;
- cancellation before and after launch acceptance;
- stable samples plus matching ACK;
- newer failing state blocking older success;
- compact Simorgh projection;
- live root overriding stale event hints;
- reconnect invalidation and state resubmission;
- full Core-to-Android command round trip;
- exact result acceptance after a newer observation arrives;
- forged observation-reference rejection;
- bounded evidence eviction;
- exact replay LRU refresh;
- conflicting replay metadata rejection;
- ordered Predicate Evidence;
- required resolved node identity;
- required `not_found` proof for `node_absent`;
- Android ledger retention after rejected result ACK.

CI builds the debug APK, runs JVM tests, runs Android lint against stable API 36, and preserves `minSdk=24`.

## 27. Galaxy A53 physical validation protocol

Physical validation remains incomplete until all of the following are recorded:

1. exact model number;
2. Android version;
3. One UI version;
4. security patch date;
5. automatic time setting and measured Core/device skew;
6. APK commit SHA;
7. target package and version;
8. Accessibility connected state;
9. overlay special-access state;
10. before stream, sequence, snapshot ID, fingerprint, and active package;
11. command ID, action ID, and command-envelope ID;
12. selected launch adapter;
13. selected IntentSender mode where applicable;
14. Android API return or exception;
15. first post-launch local snapshot;
16. stable sample count;
17. matching Core acknowledgement;
18. result and result ACK;
19. foreground front-door launch;
20. background front-door launch;
21. package-scoped URI launch;
22. lock-screen behavior;
23. battery-optimized mode;
24. unrestricted battery mode;
25. reconnect during verification;
26. Core restart while screen remains unchanged;
27. forced Android process death after launch acceptance.

Initial deterministic targets:

- Android Settings: `com.android.settings`;
- Calculator, if installed;
- Simorgh itself through package-only projection;
- a dedicated fixture application with stable front-door and deep-link destinations.

Social apps are not initial evidence targets because onboarding, account state, remote experiments, and OEM prompts make their first visible state nondeterministic.

## 28. Known follow-ups

- [#21](https://github.com/Emad211/Simorgh/issues/21): explicit fresh-observation handshake;
- [#22](https://github.com/Emad211/Simorgh/issues/22): durable Core action journal;
- [#23](https://github.com/Emad211/Simorgh/issues/23): Core/Android clock normalization.

## 29. Current boundary

This increment enables only verified `open_app`.

The next side-effect increment is semantic `click_node`, contingent on:

- fresh live-node reacquisition;
- deterministic selector resolution;
- package, visibility, enabled-state, and action-capability checks;
- documented ancestor-click policy;
- coordinate fallback as a separately controlled mode;
- fresh post-action evidence;
- deterministic fixture tests;
- Galaxy A53 physical validation.
