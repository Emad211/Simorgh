# Phase 1.8 trace limit hardening validation

## Scope

This hardening remains inside the durable correlated Trace authority. It adds no
model, provider, connector, tool, specialist, Android action, public API,
Voice, Notification, Memory, MCP or Phase 1.9 behavior.

- Canonical issue: #67.
- Implementation PR: #68.
- Base `main`: `c56ed9e039281ca0676ca36659880ea7521c25a8`.
- Validated product commit: `88f3d3e89bce394e8420498ff7d152a1d5ba7c84`.

Phase 1.9 issue #65 remains blocked until this PR is merged with exact-head Core
and Android gates green.

## Confirmed failure

`TraceEnvelope` accepts at most 100,000 events and 256 historical gap records,
but the store previously enforced only the per-record sequence constraint. A
257th distinct `trace_gap` could therefore be durably appended and only fail
later while reconstructing `TraceView`, leaving a request trace that could no
longer be queried safely.

The failure was reproduced against the extracted Phase 1.8 source snapshot:

```text
events persisted: 258
view result: TraceEnvelope ValidationError
```

## Fix

- reject a fresh append before sequence allocation when the trace already
  contains `MAX_TRACE_EVENTS` events;
- reject a fresh `trace_gap` before sequence allocation when the trace already
  contains `MAX_TRACE_GAPS` historical gaps;
- use a typed `TraceLimitError` rather than leaking a later Pydantic validation
  failure;
- preserve exact duplicate replay even when the in-memory or SQLite trace has
  reached the event limit;
- let SQLite roll rejected event-limit and gap-limit appends back without
  latching the healthy store as corrupt;
- export the reviewed trace-limit constants so store enforcement and contracts
  share one authority.

## Regression evidence

Focused tests prove:

- the 257th in-memory gap is rejected before mutation;
- the prior 256-gap `TraceView` remains byte-for-byte reconstructable;
- exact replay remains available at the event limit in both store
  implementations;
- SQLite rejects fresh event-limit and gap-limit appends transactionally;
- close/reopen produces the same baseline trace and record count.

Local zero-external validation on the extracted snapshot:

```text
focused trace-store tests: 20 passed
Core shard 1: 139 passed, 1 existing deprecation warning
Core shard 2: 122 passed
Core shard 3: 95 passed
Core shard 4: 128 passed
Core total: 484 passed
compileall: passed
Python source line-length check: passed
```

Remote one-shot validation verified the exact source Git blobs and reviewed
patch SHA-256 before mutation, removed all staging files, and passed:

```text
Ruff: passed
strict MyPy: passed across 73 source files
Core tests: 486 passed, 2 existing dependency deprecation warnings
```

The resulting PR diff contains exactly five reviewed files and no temporary
workflow, patcher, generated database, WAL/SHM file or process-lock file.

## Final gate

The ordinary owner-authored exact PR head must independently pass:

- Core installation, Ruff, strict MyPy and all tests;
- Android build, JVM tests, lint and Debug APK upload;
- zero live model/provider/connector/MCP or paid external calls;
- zero unresolved review thread or required review action.

The PR body records the exact final head, workflow run, test count and artifact
digests before Ready-for-Review and merge.
