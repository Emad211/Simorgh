# Simorgh Android

Native Android surface and future device operator for Simorgh.

## Current scope

This first shell intentionally contains only:

- a Persian RTL diagnostics screen;
- versioned device-protocol metadata;
- Android and device capability reporting;
- a buildable Compose application boundary.

Transport, accessibility observation, execution, and screen capture are implemented in subsequent work items so each boundary can be tested independently.

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
