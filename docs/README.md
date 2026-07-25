# Simorgh engineering documentation

This directory is the source of truth for runtime contracts, architecture decisions, operational behavior, validation protocols, and known limitations.

Documentation changes are part of the implementation. A state-changing capability is not complete until its contract, failure semantics, verification model, and test/physical-validation boundary are documented.

## Android compatibility and lifecycle

- [`android-compatibility.md`](android-compatibility.md) — installation baseline, runtime capability negotiation, and Android-version support tiers.
- [`ANDROID_ALWAYS_ON.md`](ANDROID_ALWAYS_ON.md) — persistent service lifecycle and Samsung/One UI setup.
- [`ANDROID_ACCESSIBILITY_OBSERVER.md`](ANDROID_ACCESSIBILITY_OBSERVER.md) — bounded Accessibility observation, node lifetime, and redaction.
- [`ANDROID_CORE_CLOCK.md`](ANDROID_CORE_CLOCK.md) — bounded Core-time estimation, monotonic action deadlines, wall-clock-jump behavior, and diagnostics.

## Device and observation transport

- [`DEVICE_TRANSPORT.md`](DEVICE_TRANSPORT.md) — authenticated device WebSocket, registration, heartbeat, reconnect, Session ownership, and clock probes.
- [`OBSERVATION_TRANSPORT.md`](OBSERVATION_TRANSPORT.md) — Accessibility snapshot schema, canonical fingerprint, monotonic local ordering, deduplication, retry, and acknowledgement.
- [`OBSERVATION_REFRESH.md`](OBSERVATION_REFRESH.md) — explicit fresh-observation handshake for unchanged screens.

## Android action execution and durability

- [`ANDROID_ACTION_TRANSPORT.md`](ANDROID_ACTION_TRANSPORT.md) — capability-gated typed command delivery, bounded Core deadlines, encrypted Android ledger, replay, cancellation, and result acknowledgement.
- [`ANDROID_ACTION_EXECUTOR.md`](ANDROID_ACTION_EXECUTOR.md) — operation contracts, deterministic selectors, predicates, and evidence.
- [`ANDROID_OPEN_APP_EXECUTOR.md`](ANDROID_OPEN_APP_EXECUTOR.md) — verified front-door and deep-link application launching.
- [`CORE_ACTION_JOURNAL.md`](CORE_ACTION_JOURNAL.md) — SQLite configuration, restart recovery, immutable identity, corruption response, and backup rules.

Current live side-effect boundary:

```text
open_app(package_name)
open_app(package_name, uri)
```

Core dispatches it only when the current Android Session advertises both:

```text
android.open_app.execution.v1
android.core_clock.bounded_estimate.v1
```

The executor capability proves that the operation exists. The clock capability proves that the Android build applies bounded Core-time and monotonic-duration semantics before crossing the launch boundary.

Click, text entry, scrolling, arbitrary gestures, global actions, screenshot transport, and visual grounding remain separate reviewed increments. Their schema types are not execution permission and Core rejects them until they receive their own versioned capability mapping.

## Architecture Decision Records

ADRs live under [`adr/`](adr/). Relevant device/runtime decisions include:

- ADR 0006 — idempotent Android action delivery;
- ADR 0007 — verified Android `open_app` execution;
- ADR 0008 — minimal Simorgh self-state observation;
- ADR 0009 — explicit observation refresh handshake;
- ADR 0010 — enforced Android action capability negotiation;
- ADR 0011 — durable Core Android action journal;
- ADR 0012 — bounded Core clock normalization on Android.

An ADR records why a design was selected, its consequences, rejected alternatives, and follow-up work. Operational documents describe how to use and validate the accepted design.

## Credential boundaries

- AvalAI and other model-provider credentials belong only on Simorgh Core.
- `SIMORGH_DEVICE_TOKEN` authenticates the private Android WebSocket.
- `SIMORGH_OPERATOR_TOKEN` authenticates trusted action and refresh APIs.
- Provider, operator, and device credentials are not interchangeable.
- Accessibility snapshots and refresh messages never carry model-provider credentials.
- The Core action journal contains operational action state but never stores provider keys or device/operator bearer tokens.
- Clock probes contain protocol identity and timing metadata only; they never contain credentials.

## Validation rules

Automated confidence is necessary but not equivalent to physical OEM validation.

For Android changes, distinguish:

1. schema and pure JVM/Python tests;
2. Core integration and WebSocket tests;
3. Android build, JVM tests, and lint;
4. generated APK artifact;
5. emulator/instrumentation evidence where available;
6. physical Samsung Galaxy A53 / One UI evidence.

Do not claim Galaxy A53 or One UI validation until the physical protocol is executed and its exact APK commit, OS/One UI versions, settings, observations, clock diagnostics, commands, and results are recorded.

## Durability and clock boundaries

- Observation refresh is safe to recreate after Core restart because it has no external side effect.
- Android action execution has an encrypted device-side write-ahead ledger.
- Core persists action identity, delivery uncertainty, cancellation, result identity, and ACK bookkeeping in a versioned SQLite journal.
- A command that may already have crossed the Android boundary is not blindly redispatched after Core restart.
- An exact Android result persisted before ACK can be acknowledged as duplicate after restart.
- New `open_app` commands require a stable bounded Core clock estimate and fail closed when uncertainty consumes the remaining deadline.
- Local observation age, capture ordering, launch ordering, and action duration use `SystemClock.elapsedRealtime()` rather than the adjustable phone wall clock.
- Each physical WebSocket reconnect creates a new clock generation; an old estimate cannot authorize a launch on the new socket.
- The complete observation registry is still process-local; a successful UI result not validated before Core restart may lack old evidence and must fail closed.

## Documentation style

- State exact supported versions and capability names.
- Separate platform acceptance from verified success.
- Document all terminal and retry states.
- Prefer typed examples over natural-language pseudocommands at execution boundaries.
- State what remains untested or process-local.
- Link follow-up issues rather than hiding known limitations.
