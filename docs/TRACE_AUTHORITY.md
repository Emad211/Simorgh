# Durable correlated trace authority

Status: Phase 1.8 implementation boundary in issue #57 / Draft PR #60.

## Purpose

The trace subsystem reconstructs one ordered, privacy-safe audit projection for a durable request. It correlates existing task, routing, context, invocation and result authorities; it does not authorize execution and is never a replacement for those stores.

```text
AgentTaskStore
  + InvocationStore
  + ContextStore
  + ResultStore
  -> deterministic source-linked TraceEventCandidate values
  -> immutable per-request sequence
  -> TraceEnvelope / TraceView
  -> exact restart reconstruction
```

A trace operation performs no model, tool, connector, specialist or Android call. It creates no reservation and commits no usage.

## Authority boundary

Trace rows may only be derived from exact retained native authorities:

- `AgentTaskStoreEntryV1` and its immutable task fingerprint;
- exact `RoutingDecision` identity and canonical hash;
- immutable `SpecialistContextBundle` identity and source manifest;
- `InvocationRecord` identity, terminal state and committed usage;
- `AuthoritativeSpecialistResult` identity and schema;
- a typed reconciliation gap when an expected retained source is absent.

Trace never stores task input, requested outcome, prompt text, context body, result body, connector response, tool arguments, provider output, artifact bytes, credentials or exception messages.

## Stable identity

- `trace_id` is UUID5 over `request_id`.
- event identity is UUID5 over trace, source-authority kind/ID, event kind and replay disposition.
- canonical event SHA-256 excludes observation and ingestion timestamps.
- durable sequence is assigned transactionally per trace.
- exact duplicate projection is idempotent.
- changed content under one event identity conflicts.

Wall-clock timestamps are observations only; they do not grant authority or alter event identity.

## Causality

The first event is a task claim or a typed missing-task gap. The reviewed zero-external vertical slice is:

```text
task_claimed
  -> routing_decided
  -> context_compiled
  -> specialist invocation_started
  -> specialist invocation_terminal
  -> result_committed
  -> trace_terminal(completed)
```

A specialist retry follows the terminal event of its exact parent invocation and carries its own context event as causation. Missing parent, context, invocation or result authority becomes a typed gap; success is never synthesized.

`result_committed` carries zero usage. Cost-bearing usage appears once on the terminal invocation event, preventing trace aggregation from double-counting a completed operation.

## Reconciliation

`reconcile_retained_trace_authority` is a deterministic startup projection over retained stores.

It:

- projects absent derivable events;
- replays exact existing events without modifying sequence or ingestion time;
- detects conflicting duplicate task, invocation, context or result identities;
- supports one or more specialist attempts and emits exactly one request terminal event;
- lets the highest retained specialist attempt control request terminal state; only a result owned by that final attempt can complete the request;
- records missing retained source authority as typed gaps;
- converts a retry or changed terminal snapshot discovered after an immutable request terminal into `SOURCE_HASH_MISMATCH` instead of rewriting history or failing startup;
- leaves model/tool producer integration and explicit terminal-supersession events for the next Phase 1.8 increment.

It cannot:

- rewrite an immutable event;
- erase or silently resolve a historical gap;
- invent terminal success;
- retry uncertain work;
- call a provider, model, tool, connector or specialist;
- reserve, release or commit budget.

## Retention

`RetentionAwareTraceStore` prunes only complete trace groups selected by reviewed policy.

- in-progress trace views are never selected;
- requests with a nonterminal durable task or nonterminal invocation are protected;
- the event currently being claimed is protected from immediate deletion;
- protection and terminal state are read again immediately before each whole-trace deletion, so an authority change cannot be deleted from an older selection snapshot;
- newest terminal traces are retained up to `SIMORGH_TRACE_STORE_MAX_TERMINAL_RECORDS`;
- pruning deletes one whole request trace transactionally;
- a trace still referenced by nonterminal authority is not removed.

The low-level `delete_trace` operation exists only on mutable store implementations and is not part of the general `TraceStore` protocol.

## SQLite store

The trace database is independent from task, invocation, result, context and Android action databases.

Runtime setting:

```text
SIMORGH_TRACE_STORE_PATH=.simorgh/traces.sqlite3
SIMORGH_TRACE_STORE_MAX_TERMINAL_RECORDS=10000
```

The SQLite authority uses:

- WAL where persistent;
- `synchronous=FULL`;
- foreign keys and busy timeout;
- exclusive process ownership;
- schema versioning;
- unique `(trace_id, sequence)`;
- indexed request and source identity;
- canonical payload SHA-256 plus indexed-column verification;
- startup integrity and causal replay validation;
- an unhealthy latch after durable database failure.

A path alias with any other Core store fails startup.

## Backup, restore and incident handling

The trace database is an independent audit projection and has its own backup target.

- Prefer a reviewed SQLite online-backup operation or stop Core before copying the database.
- Never copy only the main database while an unmatched WAL/SHM sidecar can still contain committed pages.
- Preserve the database, `-wal`, `-shm` and process-lock evidence before attempting repair.
- Restore only a complete backup with the supported schema version, then run `PRAGMA integrity_check` and a full causal `load()` before serving traffic.
- Corruption, unsupported schema or process-lock conflict blocks startup; Core does not silently replace a durable trace database with empty memory.
- Reconciliation after restore may add only derivable missing projections. It cannot retry work, erase a gap or manufacture success.
- A migration must be explicit, versioned, backup-first and covered by round-trip/reopen tests; Phase 1.8 introduces no automatic schema migration.

## Startup order

Core startup performs:

1. open invocation, result, context, Android journal and task stores;
2. reconcile task/invocation usage;
3. open raw SQLite trace authority;
4. reconcile retained source authorities into trace rows;
5. wrap the validated trace store with retention policy;
6. prune eligible terminal traces;
7. publish the store through `TraceStoreRegistry`;
8. begin serving requests.

Reconciliation runs on the raw store so startup does not rescan and prune the entire trace database after every projected event. Normal runtime appends use the retention-aware wrapper; a full retention scan runs only when a new terminal or gap event can make another trace eligible.

Candidate store validation completes before registry replacement. If loading the candidate fails, the previous healthy in-memory authority remains current and startup unwinds.

## Failure semantics

- Trace corruption or unsupported schema fails closed.
- Trace failure never mutates task, invocation, context or result source authority.
- Trace failure never triggers external retry.
- A missing source is represented as `trace_gap`, not inferred completion.
- `unknown` and `unknown_side_effect` remain honest terminal dispositions.
- Existing immutable trace rows are retained for incident analysis unless reviewed retention removes the entire terminal trace.

## Current limitations

This increment completes contracts, in-memory/SQLite authority, safe registry ownership, terminal retention and the zero-external specialist reconciliation path. Still pending in Phase 1.8:

- direct producer wiring for routing/budget/model/tool/specialist/result/cancellation events;
- complete model-classifier and governed GitHub-read trace acceptance;
- cancellation settlement projection;
- typed terminal supersession/resolution events for live post-terminal retry or cancellation transitions; startup reconciliation currently records such source advancement as `SOURCE_HASH_MISMATCH`;
- retention tombstones or external archival;
- public query API or UI, which remain out of scope;
- exact-head CI/review/merge evidence.
