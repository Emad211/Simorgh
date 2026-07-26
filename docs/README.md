# Simorgh engineering documentation

This directory is the source of truth for runtime contracts, architecture decisions, operational behavior, validation protocols, and known limitations.

Documentation changes are part of the implementation. A state-changing capability is not complete until its contract, failure semantics, verification model, and test/physical-validation boundary are documented.

## Governing architecture and implementation order

- [`SIMORGH_MASTER_DIRECTIVE.md`](SIMORGH_MASTER_DIRECTIVE.md) — authoritative mission, native authority, Hermes/OpenClaw usage boundaries, security defaults, implementation order and change control.
- [`IMPLEMENTATION_MASTER_PLAN.md`](IMPLEMENTATION_MASTER_PLAN.md) — gated step-by-step roadmap, tests and merge criteria from durable runtime through Skills, Memory, Work Graph, Gateway, Voice, Android operations, Delegation and Self-Improvement.

The implementation order is authoritative. A later product surface must not bypass unfinished native durability, policy, budget, cancellation or verification boundaries.

## Specialist agents and personal colleague runtime

- [`AGENT_RUNTIME.md`](AGENT_RUNTIME.md) — Persian-first deterministic routing, specialist policy, budgets, durable invocation behavior, model/tool gateways, traces and current limitations.
- [`AGENT_TASK_STORE.md`](AGENT_TASK_STORE.md) — durable SQLite task identity, replay, cancellation, crash recovery, integrity, retention, backup and incident handling.
- [`INVOCATION_STORE.md`](INVOCATION_STORE.md) — durable model/tool/specialist invocation identity, pre-call reservation, restart replay, uncertainty, result integrity and cost reconciliation.
- [`SPECIALIST_EXECUTION.md`](SPECIALIST_EXECUTION.md) — typed zero-external specialist execution, capability/budget intersection, durable replay, cancellation and current limitations.
- [`TYPED_RESULTS.md`](TYPED_RESULTS.md) — immutable typed result, artifact/evidence metadata, privacy, retention, canonical replay and Persian rendering authority.
- [`PERSONAL_COLLEAGUE_ARCHITECTURE.md`](PERSONAL_COLLEAGUE_ARCHITECTURE.md) — target Voice, Notification, MCP, Personal Work Graph and developer/research/SEO/marketing/sales crew architecture.

The current agent-task API selects one primary owner and persists task/routing state. PR #39 supplies the durable invocation authority; PR #44 merged the internal zero-external specialist execution runtime; PR #48 is validating the separate typed result, artifact and evidence metadata authority. The public API remains routing-only.

Common explicit and deterministic Persian routes use zero model calls. Ambiguous routing can use at most one explicitly configured, budgeted classifier invocation.

Current roadmap dependencies:

- issue #36 — complete durable native runtime and one GitHub read workflow;
- issue #38 / PR #39 — durable invocation identity and restart replay, complete;
- issue #40 / PR #44 — native typed specialist execution, complete;
- issue #46 / PR #48 — typed result, artifact and evidence authority, validating;
- issue #31 / PR #35 — Persian Voice remains parked until issue #36 prerequisites are complete;
- issue #32 — privacy-safe notification intelligence;
- issue #33 — governed MCP client registry;
- issue #34 — durable Personal Work Graph and proactive specialist crew.

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

ADRs live under [`adr/`](adr/). Relevant runtime decisions include:

- ADR 0006 — idempotent Android action delivery;
- ADR 0007 — verified Android `open_app` execution;
- ADR 0008 — minimal Simorgh self-state observation;
- ADR 0009 — explicit observation refresh handshake;
- ADR 0010 — enforced Android action capability negotiation;
- ADR 0011 — durable Core Android action journal;
- ADR 0012 — bounded Core clock normalization on Android;
- ADR 0013 — native specialist-agent runtime and deterministic cost governance;
- ADR 0014 — crash-safe durable agent-task identity and routing recovery;
- ADR 0015 — durable invocation identity, reservation and exact restart replay;
- ADR 0016 — native specialist execution authority and zero-external initial boundary;
- ADR 0017 — typed specialist result, artifact and evidence metadata authority.

An ADR records why a design was selected, its consequences, rejected alternatives, and follow-up work. Operational documents describe how to use and validate the accepted design.

## Credential and private-data boundaries

- AvalAI and other model-provider credentials belong only on Simorgh Core.
- `SIMORGH_DEVICE_TOKEN` authenticates the private Android WebSocket.
- `SIMORGH_OPERATOR_TOKEN` authenticates trusted action, refresh and specialist-task APIs.
- Provider, operator, and device credentials are not interchangeable.
- Accessibility snapshots and refresh messages never carry model-provider credentials.
- Android action, task, invocation and result stores contain operational state but never provider keys or device/operator bearer tokens.
- Invocation identity stores input fingerprints rather than prompts/tool arguments; completed typed execution payloads and authoritative typed results remain durable operational data and must be minimized by contract.
- Provider/tool exception messages are not persisted; only bounded typed failure metadata is retained.
- Clock probes contain protocol identity and timing metadata only; they never contain credentials.
- Agent traces reject configured secret/raw-content metadata and never include prompts or tool arguments by default.
- Future MCP credentials remain Core-side secret references and are never copied into specialist tasks or Android payloads.

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

For specialist-agent changes, distinguish:

1. pure contract, registry and deterministic routing tests;
2. fake provider/tool budget and restart-replay tests with zero external spending;
3. authenticated API and storage recovery tests;
4. optional live-provider staging validation under an explicit budget;
5. separately reviewed connector and mutation-executor validation.

## Durability, cost and execution boundaries

- Observation refresh is safe to recreate after Core restart because it has no external side effect.
- Android action execution has an encrypted device-side write-ahead ledger.
- Core persists Android action identity, delivery uncertainty, cancellation, result identity, and ACK bookkeeping in a versioned SQLite journal.
- Core persists agent task identity, routing state, cancellation and expiry in a separate SQLite task store.
- Core persists model/tool/specialist invocation identity, pre-call usage reservation, terminal state and typed execution payload in a separate SQLite invocation store.
- Core persists immutable final typed results plus bounded artifact/evidence metadata, privacy and retention in a separate SQLite result store.
- A routing claim interrupted by Core restart becomes `unknown`; it is not automatically routed again.
- A pending/reserved invocation interrupted by restart becomes `unknown`; an uncertain mutation becomes `unknown_side_effect`.
- Completed model/tool invocations replay without another provider/tool call or new budget reservation.
- Completed typed specialist results replay without another specialist call, result rewrite or new usage charge.
- Crash-recovered committed invocation usage is reconciled into retained parent task budgets without double counting.
- A command or invocation that may already have crossed an external boundary is not blindly redispatched after restart.
- The ungoverned direct model endpoint is disabled with HTTP 410.
- New `open_app` commands require a stable bounded Core clock estimate and fail closed when uncertainty consumes the remaining deadline.
- Local observation age, capture ordering, launch ordering, and action duration use `SystemClock.elapsedRealtime()` rather than the adjustable phone wall clock.
- Each physical WebSocket reconnect creates a new clock generation; an old estimate cannot authorize a launch on the new socket.
- The complete observation registry and traces remain process-local and fail closed when evidence is unavailable.
- Model/tool usage is reserved before invocation and reconciled afterwards; unresolved durable reservations are conservatively committed.
- Retry is not enabled by the durable invocation schema; a future retry requires a new identity and explicit budget.
- Deterministic routing and execution-critical Android infrastructure remain model-free.
- Planning output is not permission, current-state evidence or proof of side-effect completion.

## Documentation style

- State exact supported versions and capability names.
- Separate platform acceptance from verified success.
- Document all terminal and retry states.
- Prefer typed examples over natural-language pseudocommands at execution boundaries.
- State what remains untested or process-local.
- Link follow-up issues rather than hiding known limitations.
- State whether a route or operation uses a model, tool, connector or external mutation.
