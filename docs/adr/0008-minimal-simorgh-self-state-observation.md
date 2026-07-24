# ADR 0008: Minimal Simorgh self-state observation projection

- Status: Accepted
- Date: 2026-07-24
- Supersedes: the self-launch rejection described in the initial draft of ADR 0007

## Context

Android permits an Activity launch when Simorgh itself has a visible Activity. The first `open_app` design filtered every Accessibility snapshot whose active package was `ai.simorgh.android` before transport.

That created a contradiction:

1. Core's latest acknowledged observation described the previously visible external app.
2. the executor requested a fresh local snapshot while Simorgh was visible.
3. the fresh snapshot described Simorgh.
4. the canonical fingerprints necessarily differed.
5. the TOCTOU guard blocked every launch from the visible Simorgh Activity.

Transmitting Simorgh's complete UI tree was also undesirable because it could contain endpoint configuration, internal status text, and frequently changing protocol diagnostics. Those changes could create an observation → acknowledgement → UI update → observation feedback loop.

## Decision

Before device transport and action evidence comparison, a snapshot whose active package is Simorgh is projected to package-level state:

```text
schema_version       preserved
snapshot_id          preserved
captured_at_ms       preserved
active_package       preserved as ai.simorgh.android
triggering_event     removed
active_window_id     removed
root_node_id         removed
windows              empty
nodes                empty
truncation            false
max_depth             0
```

External-application snapshots are returned unchanged and preserve their complete bounded, redacted Accessibility evidence.

The same projection function is used by:

- the foreground service before observation transport;
- the local action evidence source before fingerprint comparison and verification history.

## Canonical fingerprint effect

Snapshot identity and capture time are not part of the canonical UI-state fingerprint. All Simorgh screens therefore map to one stable package-presence fingerprint.

Consequences:

- Core can acknowledge that Simorgh is the visible package;
- a fresh local self snapshot matches the Core-acknowledged state;
- changing connection/status text does not generate a new state fingerprint;
- publisher in-flight and acknowledged-fingerprint deduplication prevents a feedback loop;
- no Simorgh node text, content description, view ID, bounds, or internal control state is transported.

## Acknowledged evidence memory

Core-acknowledged evidence is stored on Android as compact metadata rather than a second full UI tree:

- stream ID;
- sequence;
- state fingerprint;
- snapshot ID;
- capture time;
- active package;
- acknowledgement time.

The full immutable local snapshot remains only in a bounded local history for deterministic predicate evaluation. This reduces memory pressure on long-running devices such as the Galaxy A53 and avoids duplicating potentially large redacted trees.

## Self-launch

`open_app` may now target Simorgh itself. It is verified through the same package-level projected state as every other launch:

- when already visible, the declared postcondition can succeed with zero attempts;
- when launched from another app, a newer projected self observation plus matching Core acknowledgement proves visibility.

Internal navigation to a specific Simorgh screen is still outside this contract. It requires an explicit internal-navigation action with its own destination postcondition.

## Consequences

### Positive

- visible-Activity background-launch eligibility is usable in practice;
- self-launch is observable without exposing self UI content;
- observation feedback is bounded by a stable fingerprint;
- transport and local TOCTOU comparison use one projection function;
- acknowledged history is compact;
- external-app evidence remains unchanged.

### Negative

- Core cannot distinguish individual Simorgh screens through Accessibility observations;
- self-state predicates are limited to package-level facts;
- a future internal-navigation feature needs a different trusted observation source;
- projection is application-specific logic that must stay synchronized between transport and execution evidence.

## Rejected alternatives

### Continue dropping all self snapshots

Rejected because it makes verified launches from a visible Simorgh Activity impossible.

### Transmit the complete Simorgh tree

Rejected because it exposes unnecessary internal UI data and creates frequent self-generated state changes.

### Disable the fresh-fingerprint check when Simorgh is visible

Rejected because it creates a special execution path with weaker TOCTOU guarantees.

### Treat Activity visibility alone as Core evidence

Rejected because the current protocol requires an acknowledged observation reference in every successful action result.

## Follow-up

- keep projection tests proving external snapshots are unchanged;
- keep a golden test proving different Simorgh screens have the same projected fingerprint;
- update the open-app executor documentation to describe projection rather than self rejection;
- introduce a separate typed internal-navigation contract before navigating to specific Simorgh screens.
