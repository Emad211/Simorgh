# Android always-on connection service

Status: implemented foundation

Simorgh owns its Android-to-Core connection inside a foreground service rather than an Activity or ViewModel. Closing the UI therefore does not intentionally close the device session.

## Runtime model

```text
MainActivity
    |
    | explicit Start / Stop
    v
SimorghConnectionService (foreground, sticky)
    |
    v
CoreWebSocketClient
    |
    v
Simorgh Core
```

The service:

- starts only after an explicit action from the application UI, except for an opt-in boot restoration;
- immediately becomes a foreground service;
- exposes an ongoing notification with a Stop action;
- owns exactly one WebSocket client;
- stores the private device token using Android Keystore-backed AES-GCM encryption;
- uses `START_STICKY` to recover after an ordinary process eviction;
- preserves an explicit user stop and does not silently reactivate it;
- can start after device boot only when the user enables the corresponding switch.

## Android-version behavior

| Android | Behavior |
|---|---|
| 7.0–7.1 | Started as a normal service and immediately promoted to foreground. |
| 8–13 | Started through `startForegroundService`; notification is posted within the service startup path. |
| 13+ | Requests `POST_NOTIFICATIONS` before the first start. A denied permission does not technically prevent the foreground service, but the user may see it only under Active apps. |
| 14–16 | Declares and starts with foreground-service type `specialUse` and the matching permission. |

`dataSync` is intentionally not used for the permanent connection because newer Android releases place time and boot-launch restrictions on that type. The private Simorgh connection is represented as a user-visible special-use service.

## Stored state

The following values are stored:

- Core WebSocket endpoint;
- encrypted device token ciphertext;
- unique encryption IV;
- connection-enabled state for sticky process recovery;
- independent start-on-boot preference.

The AES key is non-exportable and resides in Android Keystore. The AvalAI API key is never stored on Android.

## User stop semantics

Stopping from either the app or notification:

1. disables automatic service recovery;
2. closes the WebSocket;
3. removes the foreground notification;
4. stops the Android service.

Android 13 and newer also allow the user to stop the entire app from the system's Active apps interface. Simorgh must treat that as an authoritative user action, not attempt to bypass it.

## Samsung Galaxy A53 / One UI setup

Samsung's background-usage controls can place apps into Sleeping or Deep sleeping groups. Deep sleeping apps do not run in the background. For the primary A53 test device:

1. Open **Settings → Battery and device care → Battery → Background usage limits**.
2. Confirm Simorgh is not listed under **Sleeping apps** or **Deep sleeping apps**.
3. Add Simorgh to **Never auto sleeping apps** when that option is available on the installed One UI version.
4. Open **Settings → Apps → Simorgh → Battery** and select the least restrictive background option available, typically **Unrestricted**.
5. Allow notifications so the persistent connection state remains visible.

Exact labels can vary by One UI and Android release. The diagnostics and physical-device fixture must record the observed paths and settings.

## Validation scenarios

The service increment is not accepted solely because the APK builds. Physical-device validation must cover:

- connect while the app UI is visible;
- leave the Activity and verify the heartbeat continues;
- turn the screen off for 15 minutes;
- switch between Wi-Fi and mobile data;
- swipe the Activity away while leaving the service active;
- use the notification Stop action;
- restart the process and verify sticky recovery;
- restart the phone with start-on-boot disabled;
- restart the phone with start-on-boot enabled;
- stop the app through Android 13+ Active apps and verify Simorgh does not immediately fight the user action.

Each scenario records timestamps, Android/One UI build, session IDs, reconnect attempts, and Core registry state.

## Current limitations

- The status bus is process-local; a later persistent diagnostics store will retain state across process death.
- Boot restoration is code-complete but still requires physical-device evidence across supported Android versions.
- The service currently carries only device registration and heartbeat. Command delivery and Accessibility observations are separate protocol increments.
