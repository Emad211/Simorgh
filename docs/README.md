# Simorgh engineering documentation

This directory is the source of truth for runtime contracts, architecture decisions, operational behavior, validation protocols, and known limitations.

Documentation changes are part of the implementation. A state-changing capability is not complete until its contract, failure semantics, verification model, and test/physical-validation boundary are documented.

## Android compatibility and lifecycle

- [`android-compatibility.md`](android-compatibility.md) — installation baseline, runtime capability negotiation, and Android-version support tiers.
- [`ANDROID_ALWAYS_ON.md`](ANDROID_ALWAYS_ON.md) — persistent service lifecycle and Samsung/One UI setup.
- [`ANDROID_ACCESSIBILITY_OBSERVER.md`](ANDROID_ACCESSIBILITY_OBSERVER.md) — bounded Accessibility observation, node lifetime, and redaction.

## Device and observation transport

- [`DEVICE_TRANSPORT.md`](DEVICE_TRANSPORT.md) — authenticated device WebSocket, registration, heartbeat, reconnect, and Session ownership.
- [`OBSERVATION_TRANSPORT.md`](OBSERVATION_TRANSPORT.md) — Accessibility snapshot schema, canonical fingerprint, ordering, deduplication, retry, and acknowledgement.
- [`OBSERVATION_REFRESH.md`](OBSERVATION_REFRESH.md) — explicit fresh-observation handshake for unchanged screens.

## Android action execution

- [`ANDROID_ACTION_TRANSPORT.md`](ANDROID_ACTION_TRANSPORT.md) — typed command delivery, encrypted Android ledger, replay, cancellation, and result acknowledgement.
- [`ANDROID_ACTION_EXECUTOR.md`](ANDROID_ACTION_EXECUTOR.md) — operation contracts, deterministic selectors, predicates, and evidence.
- [`ANDROID_OPEN_APP_EXECUTOR.md`](ANDROID_OPEN_APP_EXECUTOR.md) — verified front-door and deep-link application launching.

Current live side-effect boundary:

```text
open_app(package_name)
open_app(package_name, uri)
```

Click, text entry, scrolling, arbitrary gestures, global actions, screenshot transport, and visual grounding remain separate reviewed increments.

## Architecture Decision Records

ADRs live under [`adr/`](adr/). Relevant device/runtime decisions include:

- ADR 0006 — idempotent Android action delivery;
- ADR 0007 — verified Android `open_app` execution;
- ADR 0008 — minimal Simorgh self-state observation;
- ADR 0009 — explicit observation refresh handshake.

An ADR records why a design was selected, its consequences, rejected alternatives, and follow-up work. Operational documents describe how to use and validate the accepted design.

## Credential boundaries

- AvalAI and other model-provider credentials belong only on Simorgh Core.
- `SIMORGH_DEVICE_TOKEN` authenticates the private Android WebSocket.
- `SIMORGH_OPERATOR_TOKEN` authenticates trusted action and refresh APIs.
- Provider, operator, and device credentials are not interchangeable.
- Accessibility snapshots and refresh messages never carry model-provider credentials.

## Validation rules

Automated confidence is necessary but not equivalent to physical OEM validation.

For Android changes, distinguish:

1. schema and pure JVM/Python tests;
2. Core integration and WebSocket tests;
3. Android build, JVM tests, and lint;
4. generated APK artifact;
5. emulator/instrumentation evidence where available;
6. physical Samsung Galaxy A53 / One UI evidence.

Do not claim Galaxy A53 or One UI validation until the physical protocol is executed and its exact APK commit, OS/One UI versions, settings, observations, commands, and results are recorded.

## Known durability boundaries

- Observation refresh is safe to recreate after Core restart because it has no external side effect.
- Android action execution has an encrypted device-side write-ahead ledger.
- Durable Core action journal and orphaned-result recovery remain tracked separately.
- Cross-device clock normalization remains tracked separately.

## Documentation style

- State exact supported versions and capability names.
- Separate platform acceptance from verified success.
- Document all terminal and retry states.
- Prefer typed examples over natural-language pseudocommands at execution boundaries.
- State what remains untested or process-local.
- Link follow-up issues rather than hiding known limitations.
