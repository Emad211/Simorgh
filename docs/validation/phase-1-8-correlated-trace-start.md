# Phase 1.8 correlated execution trace — start record

## Authority

- Tracking issue: #58.
- Parent phase: #36.
- Base: `main` after merged Context Compiler PR #56.
- Required order: Phase 1.8 precedes live-provider staging and the complete GitHub workflow.
- Voice PR #35 and all later product surfaces remain parked.

## Single trust boundary

Phase 1.8 turns the existing process-local, non-secret trace events into one durable append-only trace authority correlated across:

```text
task / route
  → context
  → specialist
  → model or tool invocation
  → typed result and evidence
  → cancellation / uncertainty
  → exact replay
```

It does not create a second task, invocation, context, result, budget or cancellation authority. Every durable event must cross-check the store that owns the transition it describes.

## Initial architecture

The implementation will preserve the existing lightweight `TraceSink` emitter interface while adding a separate durable authority:

```text
existing typed TraceEvent candidate
  → strict privacy projection
  → deterministic trace/event slot identity
  → owning-authority correlation checks
  → causal sequence allocation
  → canonical SHA-256
  → append-only TraceStore
```

Planned native components:

- immutable correlated trace contracts;
- explicit safe metadata projection rather than unrestricted durable dictionaries;
- in-memory and SQLite WAL stores;
- deterministic append/idempotency/conflict behavior;
- causal summaries and bounded metadata-only queries;
- Core lifespan/configuration integration;
- retention that protects nonterminal and uncertain work;
- focused vertical-slice tests for `github.read` route/context/tool/result/replay.

## Privacy boundary

Durable trace data may contain identities, hashes, counts, typed states, usage metadata and bounded reason codes. It must not contain task text, prompts, context/result/tool bodies, connector payloads, private repository content, credentials, arbitrary exception text, screenshots, accessibility trees, audio or notification content.

Redaction and contract validation occur before persistence. A persisted event is never repaired by deleting private fields after the fact.

## Failure semantics

- owning durable authority is written before its trace event;
- an event cannot claim a transition that disagrees with the owning store;
- identical append is idempotent;
- changed content under the same event slot conflicts;
- corruption or schema/index/hash mismatch latches the trace store unhealthy;
- replay creates trace metadata only and no model/tool/connector/specialist call or usage charge;
- ordinary CI uses only local/fake inputs and performs zero live external calls.

## First implementation checkpoint

The first checkpoint is complete when strict correlated-event contracts and in-memory/SQLite append-only stores pass unit, restart, conflict, integrity, privacy and process-lock tests without changing existing Android behavior.