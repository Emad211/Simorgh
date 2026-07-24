# Android action executor

Status: contract and deterministic resolver foundation

## Purpose

The Android action executor converts one versioned, typed command into at most one bounded device-side operation, then evaluates declared postconditions against fresh observation evidence.

It is not a natural-language agent. Planning happens in Simorgh Core. The phone receives only validated action data.

## Safety invariant

```text
No fresh unambiguous target + no verifiable postcondition = no side effect
```

A Boolean returned by `AccessibilityNodeInfo.performAction`, `dispatchGesture`, `performGlobalAction`, or `startActivity` is acceptance evidence only. It is never the final success criterion. Android documentation notes that window content can change at any time and node information can be stale; the executor therefore reacquires the current tree immediately before a node action and waits for a new bounded snapshot afterward.

## Command lifecycle

```text
Core creates typed command
        |
        v
Android validates schema and deadline
        |
        v
fresh observation precondition
        |
        v
resolve target selector
        |
        +-- not found / ambiguous --> BLOCKED
        |
        v
execute exactly one operation
        |
        v
wait for post-action observation
        |
        v
evaluate deterministic predicates
        |
        +-- satisfied ----> SUCCEEDED
        +-- unsatisfied --> FAILED
        +-- ambiguous ----> BLOCKED / INDETERMINATE
```

## Contract

Current schema version: `1.0`.

### Operations

- `open_app`
- `click_node`
- `set_text`
- `scroll_node`
- `global_action`
- `wait`

Every command contains:

- `command_id` and `action_id` UUIDs;
- issue and deadline timestamps;
- a maximum lifetime of 120 seconds;
- a fresh observation precondition;
- one discriminated operation;
- one verification policy with 1–10 typed predicates;
- a verification timeout of 250–30,000 ms;
- 1–3 required stable samples.

### Observation precondition

A command can bind itself to:

- the expected observation stream;
- a minimum stream sequence;
- an exact state fingerprint;
- an expected active package;
- a maximum observation age.

If any declared precondition fails, the executor returns `precondition_failed` before attempting an action.

## Selector model

A node selector may contain:

- package name;
- exact resource/view ID;
- normalized text criterion;
- normalized content description criterion;
- class name;
- structural path;
- semantic fingerprint;
- expected bounds;
- required fields;
- required capabilities;
- minimum score;
- minimum score margin.

At least one identity field is mandatory. If the producer does not declare a required field, validation promotes the strongest present field in this order:

1. resource ID;
2. semantic fingerprint;
3. text;
4. content description;
5. path;
6. class;
7. bounds.

### Fixed scores

| Signal | Score |
|---|---:|
| Package match | 10 |
| Exact view ID | 120 |
| Exact semantic fingerprint | 100 |
| Normalized exact text | 80 |
| Normalized contains text | 45 |
| Exact path | 60 |
| Exact class | 30 |
| Exact bounds | 40 |
| Bounds IoU ≥ 0.75 | 30 |
| Bounds IoU ≥ 0.50 | 20 |
| Each required capability | 10 |

Weights are code-owned and versioned. A model cannot alter them.

### Candidate exclusion

A node is excluded before scoring when:

- it is not visible;
- it is disabled;
- its effective package differs;
- a required capability is false;
- a required field does not match.

### Ambiguity

The resolver blocks when:

- no candidate reaches `minimum_score`; or
- the best and second-best candidates differ by less than `minimum_margin`.

This is especially important for repeated text in feeds, settings lists, social-media comments, and message threads.

## Persian normalization

The resolver and postcondition evaluator share the same text normalization:

- Unicode NFKC;
- Arabic `ي/ى/ك` to Persian `ی/ک`;
- removal of Arabic diacritics and tatweel;
- Persian and Arabic-Indic digits to ASCII digits;
- half-space, zero-width joiner, and whitespace collapse;
- optional Unicode case folding through `Locale.ROOT`.

Examples treated as equivalent by default:

```text
می‌خواهم ۱۲۳
مي خواهم 123
```

## Predicate model

Version 1 supports:

- `active_package_equals`;
- `node_exists`;
- `node_absent`;
- `node_text_equals`;
- `node_checked_equals`;
- `node_enabled_equals`.

Predicate outcomes are:

- `satisfied`;
- `unsatisfied`;
- `indeterminate`.

An ambiguous or invalid selector produces `indeterminate`. It never counts as success.

## Result evidence

A result can include:

- before and after observation references;
- selected node ID and path;
- selected score and score margin;
- up to five scored candidates;
- matched scoring signals;
- individual predicate outcomes;
- a typed failure code;
- start and finish times;
- bounded human-readable detail.

## Failure codes

- `invalid_command`
- `expired`
- `precondition_failed`
- `unsupported_capability`
- `target_not_found`
- `target_ambiguous`
- `action_rejected`
- `postcondition_failed`
- `observation_timeout`
- `cancelled`
- `internal_error`

## Planned execution adapters

### Open application

The executor will prefer an explicit package-targeted launch and catch `ActivityNotFoundException`. On Android 13/API 33 and newer, `PackageManager.getLaunchIntentSenderForPackage` is available and avoids package-visibility restrictions. Earlier versions use package-targeted launcher intents and a documented fallback.

Verification: a fresh snapshot reports the requested active package.

### Click

1. Reacquire the active Accessibility tree.
2. Resolve the selector against a fresh immutable snapshot.
3. Traverse the live tree again to the selected structural identity.
4. Request `ACTION_CLICK` when exposed.
5. If the action is rejected and the command explicitly permits it, dispatch a tap at the visible bounds center.
6. Verify declared postconditions from a newer snapshot.

Android documents direct gesture dispatch as a fallback because some apps incorrectly omit or fail `ACTION_CLICK`.

### Set text

Use `ACTION_SET_TEXT` with `ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE` only on a fresh node that is editable and exposes the action. Verification compares the visible text after normalization.

### Scroll

Prefer the node's standard Accessibility scroll action. Gesture fallback is allowed only when declared, bounds are visible, and the semantic action is unavailable or rejected.

### Global action

Back, Home, and Recents use `performGlobalAction`. On API 30 and newer, available system actions can be inspected first. A fresh package/UI postcondition remains mandatory.

## Concurrency model

- one active action per device;
- command cancellation is explicit;
- Accessibility node operations occur on the service main thread;
- network and planning never occur in Accessibility callbacks;
- live node handles never leave the immediate execution scope;
- every retry starts from a fresh observation and fresh node traversal;
- repeated state fingerprints trigger loop detection.

## Testing strategy

### Pure JVM tests

- Persian normalization;
- selector score and signal evidence;
- equal-score ambiguity;
- required-field mismatch;
- hidden and disabled exclusion;
- bounds overlap;
- predicate satisfaction, failure, and indeterminate states;
- strict polymorphic JSON round trips;
- command deadline and size bounds.

### Instrumented fixture app

A separate test application will expose deterministic controls for:

- duplicated labels;
- editable fields;
- checkbox state;
- scroll containers;
- delayed transitions;
- action rejection and gesture fallback;
- screen and orientation changes.

The fixture must use a package different from Simorgh because the production observer filters its own package.

### Galaxy A53

Physical validation must record:

- Android and One UI versions;
- target app and version;
- before observation;
- selector and candidate scores;
- chosen adapter;
- Android API return;
- after observation;
- predicate evidence;
- final typed result.

## Current boundary

The current increment defines the contracts, matcher, Persian normalizer, and postcondition evaluator only. It deliberately performs no side effects. The following PR will add command transport and live execution against newly reacquired Accessibility nodes.
