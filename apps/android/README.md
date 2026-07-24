# Simorgh Android

Native Android surface and future device operator for Simorgh.

## Current scope

This first shell intentionally contains only:

- a Persian RTL diagnostics screen;
- versioned device-protocol metadata;
- Android and device capability reporting;
- a buildable Compose application boundary.

Transport, accessibility observation, execution, and screen capture are implemented in subsequent work items so each boundary can be tested independently.

## Build requirements

- JDK 17
- Android SDK Platform 37
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
