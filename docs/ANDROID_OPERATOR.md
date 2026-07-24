# Android Operator Design

## 1. Objective

The Android Operator is the most important execution subsystem in Simorgh. Its job is to transform typed actions into reliable operations across installed applications, even when no service API exists.

The operator is not a sequence of blind coordinates. It is an observe-act-verify loop that combines Android-native mechanisms, accessibility structure, reusable application skills, screenshots, and visual grounding.

## 2. Control hierarchy

For each requested operation, the executor attempts the least fragile strategy first:

1. **Intent / deep link** — launch an app or a specific destination.
2. **Direct Android API** — alarms, timers, contacts, calendar, sharing, notifications, files.
3. **Accessibility node action** — locate a node by stable structural attributes and invoke an action.
4. **Application skill** — execute a tested workflow for a known app/version family.
5. **Vision-grounded gesture** — infer a target from the screenshot and dispatch a tap/swipe.
6. **Re-observe or request guidance** — never continue blindly after confidence falls below threshold.

## 3. Device-side modules

```text
android-operator/
  discovery/       installed packages, activities, deep links
  observation/     active window, UI tree, screenshots
  execution/       intents, node actions, gestures, text input
  verification/    post-condition evaluators
  skills/          app-specific selectors and workflows
  transport/       secure command and event channel
  recorder/        trace fixtures and replay data
```

## 4. Observations

Before and after every action, the device produces an observation:

```json
{
  "package": "com.example.app",
  "window_title": "Example",
  "timestamp": "2026-07-24T12:00:00Z",
  "ui_tree": {},
  "screenshot_ref": "artifact://...",
  "screen": {
    "width": 1080,
    "height": 2400,
    "rotation": 0
  },
  "keyboard_visible": false
}
```

The accessibility tree should be normalized to a compact representation containing only information useful for grounding and verification:

- package and class;
- resource ID;
- text and content description;
- bounds;
- clickable, editable, scrollable, selected, enabled, and focused states;
- stable parent/child relationships.

Sensitive text masking and screenshot-retention controls are implementation concerns, but raw observations must remain available during local development and evaluation when explicitly enabled.

## 5. Selector hierarchy

Node lookup uses a scored selector instead of one brittle XPath-like expression. Preference order:

1. resource ID;
2. package + semantic role + content description;
3. package + visible text + class;
4. structural relationship to a stable anchor;
5. approximate bounds from a recorded application skill;
6. visual target produced by a vision model.

A selector result includes confidence and competing candidates. Ambiguous selectors do not execute automatically.

## 6. Actions

Initial action vocabulary:

- `android.open_app`
- `android.open_uri`
- `android.tap`
- `android.long_press`
- `android.type_text`
- `android.clear_text`
- `android.swipe`
- `android.scroll`
- `android.back`
- `android.home`
- `android.wait`
- `android.notification_action`
- `android.capture_observation`

Each action is deterministic at the executor boundary. Natural-language interpretation happens upstream.

## 7. Text input

Text entry uses the following fallback sequence:

1. accessibility node `ACTION_SET_TEXT`;
2. accessibility input-method APIs where supported;
3. clipboard paste;
4. key-event or shell-based input only in explicitly enabled development modes.

Persian entry tests must cover RTL fields, mixed Persian-English text, Persian digits, emoji, multiline text, and applications that transform input.

## 8. Screen capture and vision

Android MediaProjection provides screen or application-window capture after the user starts a capture session. Accessibility screenshots may also be available depending on platform version and service configuration.

Vision is used for:

- canvases and custom-rendered controls absent from the accessibility tree;
- icon-only interfaces;
- resolving duplicate text labels;
- validating visually rendered state;
- recovering from changed layouts.

The vision model must return structured grounding data, not a prose instruction:

```json
{
  "target": "send button",
  "bounds": [910, 2140, 1050, 2290],
  "confidence": 0.94,
  "evidence": "paper-plane icon beside the message field"
}
```

## 9. Verification

An action succeeds only when its post-condition passes. Verification strategies:

- foreground package/activity comparison;
- accessibility-tree predicate;
- text/value/state predicate;
- screenshot visual predicate;
- connector/API confirmation;
- composite verification requiring multiple signals.

Examples:

- opening Slack: foreground package is Slack and a known root node exists;
- sending a message: outgoing bubble containing normalized text appears in the intended conversation;
- enabling a setting: toggle state changes and remains changed after re-observation;
- saving a draft: draft indicator or saved content is observed.

## 10. Application skills

A skill captures tested knowledge about a specific application without hard-coding it into the generic operator.

```yaml
id: slack.open_saved_items
app:
  package: com.Slack
  version_range: ">=24.0"
inputs: {}
steps:
  - action: android.open_app
    target: com.Slack
  - action: android.tap
    selector:
      text_any: ["You", "شما"]
  - action: android.tap
    selector:
      text_any: ["Later", "Save for later"]
postconditions:
  - ui_contains_any: ["Later", "Save for later"]
```

Skills are versioned, replay-tested, and allowed to declare alternative selectors for localization and UI variants.

## 11. Reliability mechanisms

- bounded retries;
- fresh observation before every retry;
- loop detection using repeated screen hashes and action history;
- timeout per action and per plan;
- app-version metadata in traces;
- idempotency controls for send, publish, create, and purchase-like operations;
- automatic fallbacks from node actions to vision;
- explicit `blocked` state when the operator cannot prove progress.

## 12. Evaluation

The operator requires a device test matrix rather than only unit tests:

- Android API levels and manufacturers;
- light/dark themes;
- Persian and English locale;
- font/display scaling;
- network delay;
- keyboard variants;
- application versions;
- interrupted flows and unexpected dialogs.

Core metrics:

- task completion rate;
- action success rate;
- false-success rate;
- median actions per task;
- recovery rate after layout change;
- average latency;
- model tokens and cost per completed task.

False success is the most serious failure class: reporting completion without verified external evidence.

## 13. Implementation milestones

### AO-0: Device handshake

Pair Android app with Simorgh Core, report capabilities, package inventory, and foreground package.

### AO-1: Native launch

Open apps and URIs through intents; verify foreground package.

### AO-2: Structured observation

Capture and normalize accessibility trees; build a local inspector UI and trace recorder.

### AO-3: Deterministic interaction

Tap nodes, set text, scroll, navigate back/home, and evaluate tree post-conditions.

### AO-4: Vision fallback

Capture screen, call a vision-capable model through AvalAI, validate structured grounding, and dispatch gestures.

### AO-5: Skill framework

Introduce reusable application skills, version matching, fixture replay, and regression tests.

### AO-6: Long workflows

Add interruption recovery, notification/event triggers, and durable multi-application missions.

## 14. Primary references

- Android AccessibilityService API: https://developer.android.com/reference/android/accessibilityservice/AccessibilityService
- Android accessibility service guide: https://developer.android.com/guide/topics/ui/accessibility/service
- Android GestureDescription API: https://developer.android.com/reference/android/accessibilityservice/GestureDescription
- Android MediaProjection guide: https://developer.android.com/media/grow/media-projection
