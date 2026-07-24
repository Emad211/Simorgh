# Android compatibility policy

Status: active engineering policy

Simorgh is a private Android agent and device operator. Compatibility therefore means more than successful APK installation: each device must explicitly report which observation and execution capabilities are available, and the Core must plan only with those capabilities.

## Supported range

| Android | API | Support tier | Expected operator capability |
|---|---:|---|---|
| 7.0–8.1 | 24–27 | Compatible | App launch, intents, accessibility tree, semantic node actions, text entry, global actions, and gesture dispatch. Screenshot acquisition may require MediaProjection or user-assisted fallback. |
| 9–10 | 28–29 | Enhanced | Compatible tier plus newer global actions and improved platform behavior. Direct accessibility screenshot capture is still unavailable. |
| 11–12L | 30–32 | Full | Direct accessibility screenshot APIs, accessibility tree, gestures, intents, and full Android Operator loop. |
| 13–16 | 33–36 | Full-current | Full tier with version-specific permission and background-execution handling. This is the primary continuous-test range. |
| 17 preview | 37 | Experimental | Compatibility lane only until the SDK and platform are stable. |

## Minimum SDK decision

`minSdk = 24` is deliberate. API 24 introduced `AccessibilityService.dispatchGesture` and `GestureDescription`, which are the lowest platform primitives that allow the operator to reproduce arbitrary touch gestures when a target app exposes no reliable semantic action.

Supporting API 23 or older would create an APK that installs but cannot provide the core promise of general app operation. Simorgh does not claim support where the central execution mechanism is absent.

## Capability negotiation

The Android client advertises versioned capabilities during device registration. The Core must not infer capability solely from model name or Android version.

Examples:

```text
android.apps.launch
android.accessibility.observe
android.accessibility.node_action
android.accessibility.gesture
android.screen.capture.accessibility
android.screen.capture.media_projection
android.notifications.observe
android.intent.execute
```

A capability is advertised only when:

1. the platform API exists;
2. the related service or permission is enabled;
3. the device/OEM implementation passes the local self-test;
4. the app implementation is production-ready.

## OEM compatibility

Android behavior differs across Samsung One UI, Xiaomi HyperOS/MIUI, Oppo/Realme ColorOS, Huawei EMUI, Pixel Android, and other OEM builds. Device compatibility is tracked by a fixture containing:

- manufacturer and model;
- Android/API version;
- OEM skin and build fingerprint;
- Simorgh app and protocol versions;
- enabled capabilities;
- power-management configuration;
- workflow success and failure classes.

Samsung Galaxy A53 5G is a primary physical test device. It launched with Android 12 and is therefore in the Full operator tier even before later OS upgrades.

## Testing matrix

### Every pull request

- compile and lint against stable API 36;
- JVM unit tests for version guards and capability selection;
- no unguarded call to an API above `minSdk`.

### Scheduled emulator tests

- API 24: minimum-install and baseline operator contracts;
- API 28: legacy enhanced behavior;
- API 30: first direct accessibility screenshot tier;
- API 33: modern permission behavior;
- API 36: current stable target.

### Physical-device tests

- Samsung Galaxy A53 5G;
- at least one Pixel/reference Android device or emulator;
- additional OEM devices as they become available.

## Compatibility rule for new features

Every new Android feature must specify:

- minimum API;
- required permission/service state;
- OEM-sensitive assumptions;
- fallback behavior;
- verification method;
- tests for the lowest supported API and current stable API.

When no safe fallback exists, the Core receives an explicit `unsupported_capability` result rather than attempting an approximate action.
