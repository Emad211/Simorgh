# Phase 1.8 trace limit hardening candidate

## Scope

This hardening remains inside the durable correlated Trace authority. It adds no
model, provider, connector, tool, specialist, Android action, public API,
Voice, Notification, Memory, MCP or Phase 1.9 behavior.

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

The exact remote PR head must still pass standard Ruff, strict MyPy, all Core
tests, Android build, JVM tests, lint and Debug APK upload before this candidate
can replace the previously green Phase 1.8 merge candidate.
