# ADR 0005: Typed Android actions and deterministic node resolution

- Status: Accepted
- Date: 2026-07-24

## Context

Simorgh receives natural-language goals, but Android execution occurs against a dynamic UI owned by another process. Accessibility nodes are short-lived, can become stale immediately, and can expose repeated labels such as multiple buttons named “ارسال”. A language model choosing screen coordinates or a node from an old snapshot would create non-deterministic and potentially destructive behavior.

The executor therefore needs a boundary that is stricter than a prompt or generic dictionary. It must determine, before any side effect, whether one fresh node is identified with enough evidence and separation from competing candidates.

The same selector machinery is also needed after execution, but verification has a different eligibility rule: a disabled visible control cannot be an action target, yet it may be exactly the post-state that a predicate needs to prove.

## Decision

Simorgh will use a versioned Android action schema with:

- discriminated, typed operations;
- an explicit observation precondition;
- one or more bounded selectors for node operations;
- fixed resolver weights controlled by code rather than the model;
- required selector fields and required action capabilities;
- minimum score and minimum top-candidate margin;
- separate action-target and verification resolution modes;
- typed postcondition predicates;
- structured resolution and predicate evidence;
- bounded command lifetime, verification timeout, and retry count;
- typed failure codes;
- equivalent validation in Core and Android before execution.

No raw natural-language instruction reaches the Android executor.

### Resolution rules

All candidates are excluded before scoring when they are:

- outside the requested package;
- not visible to the user;
- missing a required capability;
- mismatched on a required selector field.

In `ACTION_TARGET` mode, disabled nodes are also excluded. In `VERIFICATION` mode, visible disabled nodes remain eligible so predicates such as `enabled=false` can be evaluated directly.

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

### Contract parity

Core validates commands and results with strict Pydantic models. Android performs a second independent validation of UUIDs, field lengths, hashes, selector bounds, operation limits, verification predicates, result timing, evidence sizes, and failure-code consistency. This double validation prevents a malformed or differently interpreted payload from crossing the execution boundary.

## Consequences

### Positive

- Device behavior is reproducible and testable without a model.
- Model mistakes are contained by schema and resolver invariants.
- Repeated labels block instead of choosing arbitrarily.
- Persian UI text is matched consistently.
- Action traces can explain why one node was chosen.
- Postcondition evidence is machine-readable.
- A disabled post-state can be verified without making disabled nodes actionable.
- Python and Kotlin enforce the same contract meaning.

### Negative

- Selectors are more verbose than free-form instructions.
- App UI changes may cause safe `not_found` failures.
- Fixed weights require evaluation and versioning as evidence accumulates.
- Some canvas-based interfaces will require a later visual-grounding fallback.
- Two resolver modes and duplicate validation increase implementation complexity.

## Rejected alternatives

### Send natural language to the phone

Rejected because device-side interpretation would be provider-dependent, difficult to audit, and unsafe under ambiguity.

### Persist `AccessibilityNodeInfo`

Rejected because Android nodes may become stale and must be reacquired from current window content.

### Pick the highest score regardless of margin

Rejected because two nearly identical candidates are common in lists and duplicated navigation elements.

### Let the model choose weights

Rejected because execution behavior must remain stable across models and prompts.

### Exclude disabled nodes in every resolver mode

Rejected because it makes an `enabled=false` postcondition impossible to prove from the actual node.

### Treat a successful API return as action success

Rejected because `performAction` or `startActivity` acceptance does not prove the intended visible state was reached.

## Follow-up

The next increment will bind these pure contracts to fresh Android nodes, implement one-action-at-a-time execution, add command/result WebSocket messages, and require a new observation to satisfy the declared postconditions.
