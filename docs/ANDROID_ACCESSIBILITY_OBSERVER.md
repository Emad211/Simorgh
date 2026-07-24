# Android Accessibility observer

Status: local observer foundation

Simorgh uses a private `AccessibilityService` to obtain a structured representation of the active Android UI. This document covers observation only. No automatic click, text entry, gesture, or global action is implemented in this increment.

## Why structured observation comes first

A general Android operator must distinguish between:

- what is currently visible;
- which controls are semantically exposed;
- which actions each control supports;
- what changed after an operation;
- when visual grounding is required because the semantic tree is incomplete.

Executing before this observation boundary is stable would create untestable coordinate automation.

## Service configuration

The service requests:

- active-window content retrieval;
- interactive-window reporting;
- view resource IDs;
- not-important views for fuller coverage;
- future gesture capability;
- future screenshot capability on Android 11 / API 30 and newer.

Observed event classes are limited to window state/content, scrolling, text changes, focus, and clicks. Events are debounced for 150 milliseconds before a fresh tree is captured.

## Snapshot design

`AccessibilityNodeInfo` and `AccessibilityWindowInfo` objects are short-lived Android handles. Simorgh never stores them. It immediately converts them into immutable, serializable value objects.

The current flat schema contains:

- snapshot identity and capture timestamp;
- triggering event type;
- active package and window;
- window metadata and bounds;
- flat nodes linked by `node_id` and `parent_node_id`;
- deterministic tree path;
- class, resource ID, text, description, hint, and state;
- screen bounds;
- semantic and interaction flags;
- supported node actions;
- a semantic fingerprint;
- truncation evidence.

A flat node list is used instead of recursive JSON so size limits, indexing, diffing, selector scoring, and partial transport remain straightforward.

## Bounds and truncation limits

Default limits:

| Limit | Value |
|---|---:|
| Nodes per snapshot | 500 |
| Tree depth | 40 |
| Children traversed per node | 100 |
| Text per field | 512 characters |
| Actions retained per node | 40 |
| Inspector preview | 30 nodes |

When a limit is reached, the snapshot remains valid but sets `truncated=true` and records a reason such as `node_limit`, `depth_limit`, or `child_limit`.

## Sensitive text handling

If Android marks a node as a password field:

- `text` is omitted;
- `content_description` is omitted;
- `hint_text` is omitted;
- `state_description` is omitted;
- `password=true` remains so planning and verification know the field is sensitive.

This protects secrets before network transport, logging, model calls, or persistence are introduced.

## Node identity

Each node has two identifiers with different purposes:

- `node_id`: deterministic within the current window/path snapshot;
- `semantic_fingerprint`: hash of semantic and geometric attributes used for comparison and selector research.

Neither identifier is treated as a permanent handle. The real Android tree can change at any time, so future execution always obtains a fresh snapshot before resolving a target.

## Inspector

The Android diagnostics UI displays:

- whether the service is enabled and connected;
- a button to open system Accessibility settings;
- active package;
- window and node counts;
- truncation state;
- the first 30 normalized nodes.

The inspector exists to validate device/OEM behavior and create fixtures. It is not the final user experience.

## Android 7–16 behavior

Window-tree retrieval works across the supported Android 7 / API 24 to Android 16 / API 36 baseline. Direct Accessibility screenshots are a separate capability available from Android 11 / API 30. Older devices will later use an explicit MediaProjection fallback when visual grounding is required.

## Samsung Galaxy A53 validation

On the A53:

1. Install the debug APK.
2. Open Simorgh and tap **بازکردن تنظیمات Accessibility**.
3. Enable **مشاهده‌گر صفحه سیمرغ**.
4. Return to Simorgh and confirm the service reports connected.
5. Open Settings, Slack, Gmail, Chrome, and at least one Persian-language application.
6. Record package, node count, windows, truncation reasons, missing resource IDs, and Persian text preservation.
7. Verify password fields display only `<password>` in the inspector.
8. Repeat after screen rotation, split-screen where available, and One UI dialogs.

## Test strategy

Pure JVM fixtures test the normalization layer independently of Android:

- Persian whitespace normalization;
- parent/path flattening;
- password redaction;
- node and depth limits;
- closing every owned node reader after success or truncation.

Android lint and compilation validate service metadata and API guards. Physical-device evidence is required because OEMs and individual applications expose different accessibility trees.

## Next increments

1. Persist and export recorded fixtures.
2. Add versioned `device.observation` transport messages and acknowledgement.
3. Add on-demand screenshot capture for API 30+ and MediaProjection fallback.
4. Build deterministic selector scoring.
5. Add node action execution and post-condition verification.
