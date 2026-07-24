# Simorgh Android

Native Android surface and private device operator for Simorgh.

## Current scope

The application currently contains:

- a Persian RTL diagnostics screen;
- versioned device-protocol metadata;
- Android and device capability reporting;
- an authenticated WebSocket connection to Simorgh Core;
- mandatory device registration and heartbeat;
- bounded reconnect and outbound queuing;
- a sticky foreground service independent of the Activity lifecycle;
- an ongoing status notification with an explicit Stop action;
- Android Keystore-backed encryption for the private device token;
- optional restoration after device boot;
- a protected AccessibilityService that observes active app/window structure;
- bounded immutable snapshots with password-field redaction;
- a local Accessibility inspector for OEM and app diagnostics;
- ordered, rate-limited, latest-wins snapshot delivery to Core;
- reconnect-safe observation acknowledgements and retries;
- schema-versioned Android action commands and results;
- deterministic Persian-aware selector and postcondition evaluation;
- an encrypted write-ahead action ledger;
- command, cancellation, and result transport with stable replay identities;
- a verified `open_app` action executor;
- fresh pre-launch TOCTOU protection;
- launch-boundary Core-evidence revalidation;
- stable post-launch samples plus matching Core acknowledgement;
- a Persian setup surface for background app-launch special access;
- an installable Compose application boundary.

Only `open_app` is enabled as a live side effect. Click, text entry, scroll, arbitrary gestures, global actions, screenshot transport, and visual grounding remain rejected until their own reviewed increments.

## Supported Android versions

- **Installation baseline:** Android 7.0 / API 24 and newer.
- **Stable compile and target baseline:** Android 16 / API 36.
- **Preview compatibility lane:** Android 17 / API 37 is tested separately and is not allowed to destabilize the production baseline.

API 24 is the minimum because Android added `AccessibilityService.dispatchGesture` and `GestureDescription` there. These APIs are required later for a general operator when semantic node actions are unavailable.

The application uses runtime capability negotiation. Installation does not imply that every operator feature exists on every device. See [`docs/android-compatibility.md`](../../docs/android-compatibility.md).

## Build requirements

- JDK 17
- stable Android SDK Platform 36
- Android Build Tools available through the current SDK installation
- Gradle 9.5

## Build and test

```bash
gradle :apps:android:assembleDebug
gradle :apps:android:testDebugUnitTest
gradle :apps:android:lintDebug
```

The generated debug APK is located under:

```text
apps/android/build/outputs/apk/debug/
```

## Connect to Simorgh Core

Start Core with separate device and operator credentials:

```dotenv
SIMORGH_DEVICE_TOKEN=<long-random-device-token>
SIMORGH_OPERATOR_TOKEN=<different-long-random-operator-token>
SIMORGH_HOST=0.0.0.0
SIMORGH_PORT=8080
```

```bash
uvicorn simorgh_core.app:app --host 0.0.0.0 --port 8080 --reload
```

For the emulator:

```text
ws://10.0.2.2:8080/v1/devices/ws
```

For a physical phone such as Samsung Galaxy A53, use the trusted LAN address of the development computer:

```text
ws://192.168.1.20:8080/v1/devices/ws
```

Enter `SIMORGH_DEVICE_TOKEN` in the app and start the foreground service. The token is encrypted with an Android Keystore-backed AES-GCM key. AvalAI and operator credentials remain exclusively on Core or a trusted operator client.

The optional start-on-boot switch is separate from ordinary sticky-service recovery. Explicitly stopping the service disables recovery until the user starts it again.

## Enable the observer

Open Simorgh, tap **بازکردن تنظیمات Accessibility**, and enable **مشاهده‌گر صفحه سیمرغ**.

The observer:

- never persists Android node handles;
- caps nodes, depth, children, actions, and text length;
- strips semantic text from password nodes;
- excludes self-snapshots from the local inspector;
- performs no clicks, typing, gestures, or global actions in this increment.

Snapshots are projected and published from a background executor. External-app trees remain intact. Simorgh's own UI is reduced to package presence so connection fields and tokens are never transmitted.

The observation publisher:

- keeps one in-flight state and only the newest pending state;
- verifies stream, sequence, snapshot, fingerprint, and message correlation;
- retries the exact envelope up to three sends;
- pauses without consuming an attempt when the socket is unavailable;
- invalidates executable acknowledgements when the Core connection is lost;
- resubmits the latest projected state after registration on a new connection.

## Action transport

Core sends only a strict `AndroidActionCommand`; raw natural language never reaches Android execution code. Android validates the command again and records it in an encrypted write-ahead ledger before handler ownership.

Current guarantees:

- one non-terminal action per device;
- exact command-envelope replay after reconnect;
- no blind re-execution after process restart;
- a stable persisted result message ID;
- result retry without repeating the side effect;
- command/result/cancellation correlation;
- a new command remains blocked while the previous result awaits Core acknowledgement;
- malformed, oversized, wrong-device, unsupported, or unknown messages fail closed.

## Package visibility

Simorgh does **not** request `QUERY_ALL_PACKAGES` for `open_app`.

For API 24–32, the manifest declares only the two front-door intent signatures used by `PackageManager.getLaunchIntentForPackage`:

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

API 33+ uses `getLaunchIntentSenderForPackage`, which is not restricted by ordinary package visibility. The current increment does not enumerate or upload the installed-app inventory.

## Background app launch

The compatibility policy is versioned:

- API 24–28: Simorgh does not impose an overlay prerequisite;
- API 29+: Simorgh must be visible or **Display over other apps** must be granted.

A Foreground Service alone is not treated as modern background Activity-launch authorization. The guard is checked when the adapter starts and again immediately before `startActivity` or `startIntentSender`.

Without the modern prerequisite, the result is:

```text
outcome = blocked
failure_code = unsupported_capability
attempts = 0
```

The Persian diagnostics screen reports whether the special access is required and opens the best available OEM settings surface.

## Verified front-door `open_app`

```text
open_app(package_name)
```

A front-door command must include:

```json
{
  "kind": "active_package_equals",
  "package_name": "com.example.app"
}
```

Execution:

```text
latest Core-ACKed observation
        ↓
command precondition
        ↓
explicit fresh local capture
        ↓
canonical fingerprint equality
        ↓
re-read and validate current Core ACK
        ↓
already satisfied? ── yes → success, attempts=0
        ↓ no
version-aware launch adapter
        ↓
stable current local postconditions
        ↓
matching newer Core ACK
        ↓
typed ActionResult
        ↓
independent Core result validation
```

## Verified deep-link `open_app`

```text
open_app(package_name, uri)
```

An explicit URI is navigation, not merely app activation. Therefore:

- the Intent remains package-scoped with `Intent.setPackage`;
- verification must include `active_package_equals(package_name)`;
- verification must also contain at least one node predicate targeting the same package, proving the intended destination;
- node predicates for another package are rejected;
- a URI command never uses zero-attempt already-satisfied success;
- Android must accept one URI launch request and then verify fresh destination evidence;
- Core rejects a successful URI result with `attempts=0`.

## Version paths

- API 24–32: `getLaunchIntentForPackage`;
- API 33+: `getLaunchIntentSenderForPackage` and `Context.startIntentSender`;
- explicit URI: package-scoped `ACTION_VIEW`.

IntentSender background-start modes are version-specific:

- API 33: legacy boolean opt-in;
- API 34–35: `MODE_BACKGROUND_ACTIVITY_START_ALLOWED`;
- API 36+ while Simorgh is visible: `ALLOW_IF_VISIBLE`;
- API 36+ while backgrounded with overlay access: `ALLOW_ALWAYS`.

Android API acceptance is never final success. If the declared visible state is not proved before timeout, the result is failed, blocked, or timed out with typed evidence.

## Result trust boundary

A successful Android result is still a claim until Core validates it.

Core requires:

- exact command and action identity;
- exact before/after references to observations Core acknowledged;
- target-package proof;
- Predicate Evidence in the same order as the command policy;
- every Predicate Evidence outcome to be `satisfied`;
- `resolved` selector evidence with selected node identity for positive node predicates;
- `not_found` selector evidence for a successful `node_absent` predicate;
- one-attempt results to contain newer after evidence;
- URI results to report exactly one accepted launch attempt.

Core retains a bounded history of 256 compact acknowledged observations per device so a valid result remains provable even when a newer observation arrives first. Exact replay identity includes a hash of the complete observation payload; capture metadata cannot be changed under the same `message_id`.

If evidence is unknown, evicted, conflicting, or malformed, Core sends `device.action_result_ack(status=rejected)` and does not record terminal success. Android keeps the result in its encrypted ledger and blocks later actions rather than silently accepting an unverifiable side effect.

## Known follow-ups

- [#21](https://github.com/Emad211/Simorgh/issues/21): explicit fresh-observation handshake for unchanged screens;
- [#22](https://github.com/Emad211/Simorgh/issues/22): durable Core action journal and restart recovery;
- [#23](https://github.com/Emad211/Simorgh/issues/23): Core/Android clock normalization.

The default observation-age budget remains strict until #21 is implemented. Absolute clock skew remains a documented limitation until #23 is implemented.

## Documentation

- [`docs/DEVICE_TRANSPORT.md`](../../docs/DEVICE_TRANSPORT.md) — device channel;
- [`docs/OBSERVATION_TRANSPORT.md`](../../docs/OBSERVATION_TRANSPORT.md) — observation ordering, fingerprinting, retry, and validation;
- [`docs/ANDROID_ACTION_TRANSPORT.md`](../../docs/ANDROID_ACTION_TRANSPORT.md) — ledger, replay, cancellation, and result delivery;
- [`docs/ANDROID_ACTION_EXECUTOR.md`](../../docs/ANDROID_ACTION_EXECUTOR.md) — typed operations, selectors, and postconditions;
- [`docs/ANDROID_OPEN_APP_EXECUTOR.md`](../../docs/ANDROID_OPEN_APP_EXECUTOR.md) — complete verified launch state machine;
- [`docs/ANDROID_ALWAYS_ON.md`](../../docs/ANDROID_ALWAYS_ON.md) — lifecycle and Samsung setup;
- [`docs/ANDROID_ACCESSIBILITY_OBSERVER.md`](../../docs/ANDROID_ACCESSIBILITY_OBSERVER.md) — snapshot schema and validation plan.

## Package

```text
ai.simorgh.android
```

## Rules

- Model-provider keys never belong in the Android application.
- Protocol messages are versioned.
- Device capabilities are explicitly advertised rather than inferred from installation.
- State-changing actions require pre/post observations and verification.
- New Android APIs require SDK guards and a documented fallback.
- Production transport must use `wss://`; local `ws://` is debug-only.
- A permanent connection remains user-visible and immediately stoppable.
- Accessibility nodes are short-lived input data, never durable action handles.
- Observation and result transports own separate bounded retry state machines.
- An uncertain action after process restart is blocked, never blindly replayed.
- Android launch API return is acceptance evidence only; postconditions determine success.
- Physical Galaxy A53 validation must be recorded before claiming OEM validation.
