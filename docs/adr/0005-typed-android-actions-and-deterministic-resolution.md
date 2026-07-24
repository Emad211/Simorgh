# ADR 0005: Typed Android actions and deterministic node resolution

- Status: Accepted
- Date: 2026-07-24

## Context

Simorgh receives natural-language goals, but Android execution occurs against a dynamic UI owned by another process. Accessibility nodes are short-lived, can become stale immediately, and can expose repeated labels such as multiple buttons named “ارسال”. A language model choosing screen coordinates or a node from an old snapshot would create non-deterministic and potentially destructive behavior.

The executor therefore needs a boundary that is stricter than a prompt or generic dictionary. It must determine, before any side effect, whether one fresh node is identified with enough evidence and separation from competing candidates.

## Decision

Simorgh will use a versioned Android action schema with:

- discriminated, typed operations;
- an explicit observation precondition;
- one or more bounded selectors for node operations;
- fixed resolver weights controlled by code rather than the model;
- required selector fields and required action capabilities;
- minimum score and minimum top-candidate margin;
- typed postcondition predicates;
- structured resolution and predicate evidence;
- bounded command lifetime, verification timeout, and retry count;
- typed failure codes.

No raw natural-language instruction reaches the Android executor.

### Resolution rules

A candidate is excluded before scoring when it is:

- outside the requested package;
- not visible to the user;
- disabled;
- missing a required capability;
- mismatched on a required selector field.

Remaining candidates receive fixed scores for exact resource ID, semantic fingerprint, normalized text, content description, path, class and bounds overlap. The resolver selects a node only when:

1. the top score meets the selector minimum; and
2. the difference between the first and second candidates meets the minimum margin.

Otherwise the result is `not_found`, `ambiguous`, or `invalid_selector`. An ambiguous result is never converted into a coordinate tap.

### Persian text

Text comparison uses one deterministic normalizer for selection and verification. It performs Unicode NFKC normalization, Arabic-to-Persian `ی/ک` normalization, Arabic diacritic removal, Persian and Arabic digit normalization, whitespace and half-space normalization, and optional case folding for mixed Persian-English text.

### Verification

An action command includes typed predicates such as:

- active package equals;
- node exists or is absent;
- node text equals;
- checked state equals;
- enabled state equals.

A fresh post-action snapshot is evaluated by deterministic code. Ambiguous predicate resolution is `indeterminate`, not success.

## Consequences

### Positive

- Device behavior is reproducible and testable without a model.
- Model mistakes are contained by schema and resolver invariants.
- Repeated labels block instead of choosing arbitrarily.
- Persian UI text is matched consistently.
- Action traces can explain why one node was chosen.
- Postcondition evidence is machine-readable.

### Negative

- Selectors are more verbose than free-form instructions.
- App UI changes may cause safe `not_found` failures.
- Fixed weights require evaluation and versioning as evidence accumulates.
- Some canvas-based interfaces will require a later visual-grounding fallback.

## Rejected alternatives

### Send natural language to the phone

Rejected because device-side interpretation would be provider-dependent, difficult to audit, and unsafe under ambiguity.

### Persist `AccessibilityNodeInfo`

Rejected because Android nodes may become stale and must be reacquired from current window content.

### Pick the highest score regardless of margin

Rejected because two nearly identical candidates are common in lists and duplicated navigation elements.

### Let the model choose weights

Rejected because execution behavior must remain stable across models and prompts.

### Treat a successful API return as action success

Rejected because `performAction` or `startActivity` acceptance does not prove the intended visible state was reached.

## Follow-up

The next increment will bind these pure contracts to fresh Android nodes, implement one-action-at-a-time execution, add command/result WebSocket messages, and require a new observation to satisfy the declared postconditions.
