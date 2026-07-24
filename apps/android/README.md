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

Only `open_app` is enabled as a live side effect. Click, text entry, scroll, gestures, global actions, screenshot transport, and visual grounding remain rejected until their separate reviewed increments.

## Supported Android versions

- **Installation baseline:** Android 7.0 / API 24 and newer.
- **Stable compile and target baseline:** Android 16 / API 36.
- **Preview compatibility lane:** Android 17 / API 37 is tested separately and is not allowed to destabilize the production baseline.

API 24 is the minimum because Android added `AccessibilityService.dispatchGesture` and `GestureDescription` there. These are required for a general operator to perform reliable touch gestures when semantic node actions are unavailable.

The application uses runtime capability negotiation. A device is never assumed to support every operator feature merely because the APK can be installed. See [`docs/android-compatibility.md`](../../docs/android-compatibility.md).

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

For the emulator, use:

```text
ws://10.0.2.2:8080/v1/devices/ws
```

For a physical phone such as Samsung Galaxy A53, use the development computer's trusted LAN address:

```text
ws://192.168.1.20:8080/v1/devices/ws
```

Enter `SIMORGH_DEVICE_TOKEN` in the app and start the foreground service. The token is encrypted with an Android Keystore-backed AES-GCM key; the AvalAI and operator keys remain exclusively on Core or the trusted operator client.

The optional start-on-boot switch is separate from ordinary sticky-service recovery. Stopping the service explicitly disables recovery until the user starts it again.

## Enable the observer

Open Simorgh and tap **بازکردن تنظیمات Accessibility**, then enable **مشاهده‌گر صفحه سیمرغ**. Return to Simorgh to inspect the latest external-app snapshot.

The observer:

- never stores Android node handles;
- caps nodes, depth, children, actions, and text length;
- strips semantic text from password nodes;
- ignores self-snapshots in the inspector;
- performs no clicks, typing, gestures, or global actions in the current increment.

When the foreground service is connected, snapshots are projected and published from a background executor. External-app trees remain intact; Simorgh's own UI is reduced to package presence so connection fields are never transmitted. The publisher keeps one in-flight state and only the newest pending state, verifies a correlated acknowledgement, retries the exact envelope up to three sends, and pauses without consuming an attempt when the socket is unavailable.

Executable acknowledged evidence is invalidated when the Core connection is lost. After registration on a new connection, the most recent projected state is submitted again even when the visible screen did not change. This prevents actions from using an acknowledgement belonging to a previous Core session.

## Action transport

Core sends only a strict `AndroidActionCommand`; raw natural language never reaches Android execution code. Android validates the command again and records it in an encrypted write-ahead ledger before asking the installed handler to accept ownership.

Current transport guarantees:

- one non-terminal action per device;
- exact command-envelope replay after reconnect;
- no blind re-execution after process restart;
- a stable persisted result message ID;
- result retry after disconnect without repeating the action;
- command/result/cancellation correlation;
- a new command remains blocked while the prior result awaits Core acknowledgement;
- malformed, oversized, wrong-device, unsupported, or unknown messages fail closed.

## Enable autonomous app launch

Android 10 and newer restrict background Activity starts. A Foreground Service alone is not enough to open another app. Simorgh allows a launch only when:

- the Simorgh Activity is currently visible; or
- **Display over other apps** special access is granted.

The Persian diagnostics screen shows the current state and opens the app-specific, general overlay, or general Android settings page as supported by the OEM. Without this access, a background `open_app` command returns a typed `blocked / unsupported_capability` result and performs no launch.

This special access is a launch prerequisite only. A successful result still requires a fresh visible postcondition and a matching Core acknowledgement.

## Verified `open_app`

The live handler supports:

```text
open_app(package_name)
open_app(package_name, uri)
```

Execution path:

```text
latest Core-ACKed observation
        ↓
command precondition
        ↓
explicit fresh local capture
        ↓
canonical fingerprint equality
        ↓
re-read current Core ACK and validate again
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
```

If the connection invalidates the acknowledgement between the first check and the launch boundary, the operation returns `blocked / precondition_failed` with `attempts=0`.

Version paths:

- API 24–32: `getLaunchIntentForPackage`;
- API 33+: `getLaunchIntentSenderForPackage` and `Context.startIntentSender` with explicit sender opt-in options;
- explicit URI: package-scoped `ACTION_VIEW`.

Android API acceptance is never treated as final success. If the target does not become observably correct before timeout, the result is failed, blocked, or timed out with structured evidence.

The default observation freshness budget is intentionally strict. Issue [#21](https://github.com/Emad211/Simorgh/issues/21) tracks an explicit unchanged-state refresh handshake; the implementation must not weaken freshness by silently increasing `maximum_age_ms`.

See [`docs/ANDROID_OPEN_APP_EXECUTOR.md`](../../docs/ANDROID_OPEN_APP_EXECUTOR.md) for the complete state machine, failure matrix, official Android references, and Galaxy A53 validation protocol.

## Documentation

- [`docs/DEVICE_TRANSPORT.md`](../../docs/DEVICE_TRANSPORT.md) — device channel;
- [`docs/OBSERVATION_TRANSPORT.md`](../../docs/OBSERVATION_TRANSPORT.md) — ordering, fingerprinting, retry, and validation;
- [`docs/ANDROID_ACTION_TRANSPORT.md`](../../docs/ANDROID_ACTION_TRANSPORT.md) — command, ledger, replay, cancellation, and result semantics;
- [`docs/ANDROID_ACTION_EXECUTOR.md`](../../docs/ANDROID_ACTION_EXECUTOR.md) — typed operations, selectors, and verification;
- [`docs/ANDROID_OPEN_APP_EXECUTOR.md`](../../docs/ANDROID_OPEN_APP_EXECUTOR.md) — verified app launching;
- [`docs/ANDROID_ALWAYS_ON.md`](../../docs/ANDROID_ALWAYS_ON.md) — lifecycle and Samsung setup;
- [`docs/ANDROID_ACCESSIBILITY_OBSERVER.md`](../../docs/ANDROID_ACCESSIBILITY_OBSERVER.md) — snapshot schema and validation plan.

## Package

```text
ai.simorgh.android
```

## Rules

- Model-provider keys never belong in the Android application.
- Protocol messages are versioned.
- Device capabilities are explicitly advertised rather than assumed by the server.
- State-changing device actions require pre/post observations and verification.
- New Android APIs must be guarded by SDK checks and have a documented fallback.
- Production transport must use `wss://`; local `ws://` is debug-only.
- A permanent connection must remain user-visible and immediately stoppable.
- Accessibility nodes are short-lived input data, never durable action handles.
- Observation messages bypass the generic reconnect queue and use their own latest-wins state machine.
- Action results bypass the generic reconnect queue and use a stable persisted delivery identity.
- An uncertain active action after Android process restart is blocked, never blindly replayed.
- A background Activity launch without a visible Simorgh window or overlay special access is blocked.
- An Android launch API return is acceptance evidence only; postconditions determine success.
