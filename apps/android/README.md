# Simorgh Android

Native Android surface and future device operator for Simorgh.

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
- a single-handler boundary for the future live executor;
- an installable Compose application boundary.

The action transport deliberately installs no side-effect executor yet. App launch, node reacquisition, click, text entry, scroll, gesture, global action, screenshot transport, and post-action observation waiting are implemented in separate reviewed increments.

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
- performs no clicks, typing, gestures, or global actions in the current transport increment.

When the foreground service is connected, external-app snapshots are published from a background executor. The publisher keeps one in-flight state and only the newest pending state, verifies a correlated acknowledgement, retries the exact envelope up to three sends, and pauses without consuming an attempt when the socket is unavailable.

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

Until the first real handler is installed, typed commands are returned as `rejected` rather than being silently ignored.

See:

- [`docs/DEVICE_TRANSPORT.md`](../../docs/DEVICE_TRANSPORT.md) for the device channel;
- [`docs/OBSERVATION_TRANSPORT.md`](../../docs/OBSERVATION_TRANSPORT.md) for ordering, fingerprinting, retry, and validation;
- [`docs/ANDROID_ACTION_TRANSPORT.md`](../../docs/ANDROID_ACTION_TRANSPORT.md) for command, ledger, replay, cancellation, and result semantics;
- [`docs/ANDROID_ACTION_EXECUTOR.md`](../../docs/ANDROID_ACTION_EXECUTOR.md) for typed operations, selectors, and verification;
- [`docs/ANDROID_ALWAYS_ON.md`](../../docs/ANDROID_ALWAYS_ON.md) for lifecycle and Samsung setup;
- [`docs/ANDROID_ACCESSIBILITY_OBSERVER.md`](../../docs/ANDROID_ACCESSIBILITY_OBSERVER.md) for the snapshot schema and validation plan.

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
