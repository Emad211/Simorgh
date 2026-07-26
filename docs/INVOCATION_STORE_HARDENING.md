# PR #39 invocation-store hardening addendum

Status: implemented by the PR #39 hardening bundle; acceptance still requires exact-head Core and Android CI.

## Scope

This addendum remains inside Phase 1 Step 1.2. It opens no specialist execution, live connector, MCP, Voice, Notification, retry, mutation executor or new Android action boundary.

## Schema version 2

Invocation payload and SQLite store schema are bumped from provisional version 1 to version 2 because model input identity now fingerprints the typed request independently from the selected provider/model target. The target remains a separate immutable field.

A provisional version-1 database cannot be migrated safely because the original request-only fingerprint cannot be reconstructed from the stored target-inclusive hash. Startup therefore fails closed on version 1. Since Step 1.2 has not been released, development databases from earlier Draft heads must be archived or removed explicitly; production migration is not claimed.

## Exclusive process ownership

A file-backed invocation store acquires a non-blocking operating-system lock at:

```text
<invocation-store-path>.lock
```

The lock is held for the lifetime of `SQLiteInvocationStore`. A second owner fails before SQLite recovery runs. The lock file is retained, while the operating-system lock itself is released on close or process exit.

This protects one invocation-store path. A future Core-wide lease may extend ownership across independently configured durable authorities.

## Strict canonical JSON

Canonical payloads require:

- a top-level object;
- string object keys at every depth;
- only JSON null, booleans, integers, finite floats, strings, lists and objects;
- maximum nesting depth 100;
- sorted keys, compact separators and preserved Unicode;
- `NaN`, infinities, tuples, arbitrary objects and non-string keys are rejected;
- serialization failures return one generic typed error without private value or chained cause.

Tool arguments are limited to 256000 canonical UTF-8 bytes before invocation identity is claimed. Completed invocation results remain limited by the invocation payload limit.

## Catalog-independent completed replay

A completed model invocation is looked up before current catalog selection. Exact request identity is validated against the durable record, while the original provider/model target is read from that immutable record. Therefore removal or disabling of the old model does not force another provider call or invalidate a completed replay.

Provisional version-1 target-inclusive fingerprints are not accepted under schema version 2.

## Cancellation and transport uncertainty

After durable reservation, provider/tool transport failure or coroutine cancellation is treated as uncertainty:

```text
reserved read/proposal → unknown
reserved mutation      → unknown_side_effect
```

The gateway attempts both operations even when one fails:

1. persist invocation uncertainty and conservative committed usage;
2. settle the process-local parent request reservation.

If task cancellation already cleared the process-local reservation, the durable invocation remains detailed cost authority and startup reconciliation raises the retained parent task aggregate. No automatic retry occurs.

A full task-to-child cancellation index and adapter cancellation orchestration remain Phase 1 Step 1.6.

## Distinct durable paths

Core startup rejects a configuration in which Android action, agent-task and invocation authorities resolve to the same file path. The invocation authority is opened first so its process lock is acquired before recovery of other stores.

## Required merge evidence

Before ADR 0015 becomes Accepted and PR #39 merges, the exact Head must pass:

- patch preflight and idempotent rerun;
- Core Ruff;
- strict MyPy;
- all Core tests, including process-lock subprocess tests;
- Android build;
- Android JVM tests;
- Android lint;
- debug APK generation;
- review-thread audit;
- confirmation that ordinary CI performs no live model, connector or MCP call.

## Exact accounting boundary before specialist execution

Startup reconciliation currently raises each retained task aggregate component-wise
to at least the sum visible in the durable invocation ledger. This is not a permanent
attribution model for a mixture of historical unattributed task usage and new
invocation-attributed usage. Before specialist execution is enabled, accounting must
separate legacy/unattributed usage from invocation-ledger usage or derive the
aggregate entirely from durable invocation identities. PR #39 makes no exact
cross-era accounting claim.

## Explicit remaining limits

- no specialist execution runtime;
- no live GitHub connector;
- no retry API;
- no full cancellation propagation;
- no result-artifact authority beyond the current typed invocation result;
- no application-level encryption of invocation payloads;
- no terminal retention/tombstone policy;
- no distributed or multi-process Core lease beyond the invocation path lock;
- no physical Galaxy A53 claim.
