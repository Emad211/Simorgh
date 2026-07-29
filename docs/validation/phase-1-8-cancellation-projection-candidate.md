# Phase 1.8 typed cancellation projection candidate

## Boundary

This increment projects durable `TaskCancellationResult` authority into the correlated request trace. It does not initiate cancellation, retry an invocation, call a provider/adapter, or mutate task/invocation authority.

## Clean product commit

- Commit: `3f6d4b5571f34566b1915eeb589ff3d66b7fbafb`
- Direct parent: `6e2a7d3fcc131bf84b6179d49a655a27a47d7e70`
- Candidate CI run: `30500677057`
- Product diff: exactly four files
- Temporary patcher and workflow changes are absent from the clean commit

## Implemented semantics

- accepted cancellation without a durable settlement result keeps the trace open;
- settled cancellation creates a typed `cancellation_settled` event before request terminal;
- retained replay authority creates `cancellation_replayed` linked to the original event;
- ordinary settlement terminates as `cancelled`;
- any reserved invocation with uncertain cancellation outcome terminates conservatively as `unknown_side_effect`;
- cancellation identity and canonical authority hash are retained;
- only settled/uncertain invocation counts are copied into trace details;
- operator reason, per-invocation outcome payloads, provider acknowledgement content and task body are excluded;
- a legacy cancelled task without typed cancellation authority preserves the previous generic cancelled terminal behavior;
- a changed terminal snapshot remains an explicit `source_hash_mismatch` gap;
- cancellation parent identity is stable across live replay and restart: task claim when routing is absent, routing event otherwise.

## Covered acceptance

- typed privacy-safe cancellation settlement;
- uncertainty disposition;
- replay linkage with zero new usage;
- accepted-but-unsettled cancellation remains nonterminal;
- settlement precedes request terminal;
- SQLite close/reopen reconciliation is exactly idempotent;
- duplicate cancellation API replay does not create an event conflict;
- cancellation survives Core restart;
- prior source-evolution and legacy cancellation tests remain valid.

## Required exact-head validation

The standard repository CI must pass on the commit containing this record:

```text
ruff check .
mypy services/core/src
pytest
Android assembleDebug
Android JVM tests
Android lint
Debug APK upload
```

Phase 1.8 remains Draft after this checkpoint. Typed live terminal supersession/resolution and final runtime-composition/operations evidence are still pending.
