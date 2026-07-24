# ADR 0003: Use a hybrid Android observation and control strategy

- Status: Accepted
- Date: 2026-07-24

## Context

No single Android mechanism reliably operates every application:

- intents and deep links are precise but limited to exposed destinations;
- accessibility trees are structured but may omit custom-rendered controls;
- screenshots represent visible state but require visual grounding;
- absolute coordinate scripts are fragile across devices and layout changes.

The system must also distinguish true completion from an action that merely executed without reaching the desired state.

## Decision

The Android Operator uses an ordered hybrid strategy:

1. intent, deep link, or direct Android API;
2. accessibility-node selection and action;
3. tested application skill;
4. screenshot-based visual grounding and gesture dispatch.

Every state-changing action captures a post-observation and evaluates one or more typed post-conditions. Coordinate-only actions without subsequent verification are not considered successful.

## Consequences

### Positive

- broader application coverage;
- lower cost and latency for structurally accessible screens;
- vision is reserved for interfaces that need it;
- measurable recovery from interface changes;
- false-success failures become observable.

### Negative

- device-side implementation is more complex;
- traces and fixtures require storage and tooling;
- hybrid confidence and fallback policies require empirical tuning;
- application-version changes require ongoing regression tests.

## Evaluation requirement

Node-only, vision-only, and hybrid approaches must be benchmarked on the same recorded tasks. The chosen strategy is driven by task completion rate, false-success rate, latency, and cost rather than intuition.
