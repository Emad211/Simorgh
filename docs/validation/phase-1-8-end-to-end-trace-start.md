# Phase 1.8 End-to-End Trace — start record

## Status

- Phase: 1.8.
- State: active implementation boundary; merge evidence not yet available.
- Tracking issue: #59 (canonical; #57 was the earlier duplicate).
- Draft PR: #60.
- Base branch: `main`.
- Exact Phase 1.7 merge authority: `dab5333140da2d9cf9b982a57ede1a2d08397cf1`.
- Rebased start point: `5f3e7ee1a0655561dbf925a0cf44994b2abacdf5`; later `main` commits after the Phase 1.7 merge had zero net repository-content change.
- Working branch: `core/end-to-end-trace`.

## Objective

Replace the current process-local collection of privacy-oriented trace events with one durable, versioned and causally correlated audit projection per request.

The completed Phase 1.8 boundary must reconstruct after Core restart an ordered, non-secret timeline across:

```text
durable task/routing
  → budget reservation/reconciliation
  → context compile/replay
  → specialist/model/tool invocation
  → typed result commit/replay
  → cancellation, uncertainty or terminal disposition
```

Trace remains a projection of existing durable authorities. It cannot authorize work, mutate task/invocation/context/result state, hide uncertainty or invent completion.

## Current repository audit

At the Phase 1.7 merge authority:

- `TraceEventKind` already names routing, budget, model, tool, specialist, result, cancellation and context events;
- `TraceEvent` carries request/invocation IDs, bounded scalar metadata, usage, cache, outcome and reason;
- metadata keys containing known private/credential fragments are rejected;
- `NullTraceSink` and bounded `InMemoryTraceSink` are the only sink authorities;
- `event_id` is random UUID4;
- ordering is process-local list/wall-clock order;
- trace events are lost on Core restart;
- there is no stable request-level trace ID, durable sequence, causal parent, source-authority hash or typed event-detail registry;
- there is no SQLite trace store, reconciliation, completeness/gap model, bounded terminal retention or independent lifespan path;
- current producers emit useful local events, but no durable mechanism proves one complete route-to-result/replay chain.

## Approved implementation sequence

### 1. Contracts and event-detail registry

Introduce strict immutable contracts for:

- stable request trace identity;
- stable event identity;
- source authority identity/hash;
- durable per-trace sequence;
- causal parent/causation links;
- replay/cache/usage/outcome disposition;
- typed event-family details;
- trace completeness, gap and terminal disposition;
- privacy and retention classification.

Arbitrary persisted metadata dictionaries are not authoritative. Every event kind must map to one reviewed typed detail family.

### 2. Pure in-memory authority

Build a strict in-memory trace store first and prove:

- exact duplicate idempotence;
- changed-content conflict;
- stable IDs independent of timestamp/restart;
- monotonic sequence;
- causal and cross-request validation;
- replay adds no usage;
- no private body/credential admission;
- terminal/gap reconstruction from source-linked events.

### 3. SQLite WAL authority

Add an independent SQLite trace store with:

- WAL and synchronous full durability;
- schema/version/hash/index integrity;
- exclusive process ownership;
- unhealthy latch;
- restart replay;
- path-alias protection against task, invocation, result, context and Android stores;
- bounded terminal retention that protects nonterminal authority;
- documented backup/recovery/migration behavior.

### 4. Source-authority projection and reconciliation

Project events only from exact retained durable task, invocation, context and result records or explicitly typed local observations.

Startup reconciliation may add an absent derivable projection, but it cannot:

- rewrite an immutable event;
- synthesize terminal success;
- erase a gap;
- call a model/tool/connector/specialist;
- reserve or commit usage;
- retry uncertain work.

### 5. Producer integration

Correlate the existing boundaries:

- routing and task terminal states;
- budget reservation/reconciliation;
- model/tool/specialist invocation and replay;
- context compilation/replay/failure;
- result commit/replay/failure;
- cancellation settlement/replay;
- explicit unknown/unknown-side-effect/gap outcomes.

The trace sink/store remains an audit projection and never supersedes the owning authority.

### 6. Lifespan, operations and validation

Add:

- independent trace-store configuration and Core lifespan ownership;
- operational guide;
- ADR for durable causal trace projection;
- privacy/retention/incident response;
- deterministic zero-external acceptance tests;
- exact-head Core and Android CI validation.

## Required first vertical slice

The first acceptance path will be a deterministic zero-external planning task:

```text
task claim
  → deterministic route
  → context bundle
  → zero-external specialist
  → authoritative typed result
  → reconstructed durable trace after restart
```

It must prove:

- stable trace/event identities;
- exact source authority linkage;
- correct causal order;
- no duplicated usage on replay;
- no private task/context/result body in trace rows, errors or logs;
- exact reconstruction after SQLite reopen;
- honest incomplete/unknown disposition when a required source stage is absent.

A governed GitHub read trace path is added only after the zero-external authority is correct.

## Merge gates

Phase 1.8 cannot merge until:

- issue #57 Definition of Done is fully satisfied;
- strict typed contracts and event-detail registry are documented;
- in-memory and SQLite parity/restart/corruption/lock/retention tests pass;
- end-to-end deterministic route → context → specialist → result/replay trace passes;
- cancellation and uncertainty remain conservative;
- no arbitrary private metadata survives into durable trace authority;
- ordinary CI performs zero live model/provider/connector/MCP calls;
- Core Ruff, strict MyPy and all tests pass on the exact PR head;
- Android build, JVM tests, lint and Debug APK pass on the same exact head;
- no unresolved review thread remains;
- final validation record identifies exact head, run and artifact evidence.

## Explicit non-goals

- no OpenTelemetry or vendor exporter;
- no public trace endpoint or dashboard;
- no task/prompt/evidence/context/result body storage;
- no live provider staging;
- no complete GitHub report workflow;
- no mutation or new Android action;
- no Voice, Notification, Scheduling, Channels, Delegation, MCP, Memory, Personal Work Graph or self-improvement.
