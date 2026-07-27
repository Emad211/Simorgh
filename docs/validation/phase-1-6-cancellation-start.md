# Phase 1.6 cancellation propagation — start record

Status: implementation completed in PR #54 candidate; superseded for acceptance evidence by [`phase-1-6-cancellation-propagation.md`](phase-1-6-cancellation-propagation.md).

## Authority

- Parent roadmap: #36.
- Tracking issue: #53.
- Branch: `core/cancellation-propagation`.
- Base merge commit: `7fef6a5262de1e84be89c9afc30c25053945a4ac`.

## Initial architecture decision

The durable agent-task record remains the source of truth for cancellation. The invocation store will gain a derived durable cancellation fence keyed by task `request_id` so that invocation `begin` and `reserve` can fail closed under the same lock/transaction that owns invocation state.

Required race property:

```text
invocation begins/reserves before fence
  → cancellation snapshot enumerates and settles it

cancellation fence commits first
  → later invocation begin/reserve is rejected
```

This avoids a second task authority while providing an atomic invocation admission boundary.

## Existing foundations confirmed

- durable task state already supports `cancelled` plus a cancelled budget snapshot;
- invocation records already own request ID, kind, effect, optional parent ID, pending/reserved/terminal states and conservative `unknown`/`unknown_side_effect` settlement;
- specialist requests already derive a stable cancellation-owner ID;
- specialist execution already accepts a cooperative cancellation token;
- SQLite invocation recovery already treats interrupted pending/reserved work conservatively.

## Missing boundary to implement

- typed idempotent cancellation request/result;
- durable task cancellation metadata and conflict detection;
- invocation-store cancellation fence and owned-invocation enumeration;
- immutable cancellation-owner identity on invocation claims;
- process-local owner registry with late-registration blocking;
- coordinated task-to-invocation propagation service;
- typed optional adapter cancellation acknowledgement;
- privacy-safe cancellation traces;
- restart, race, accounting and integration tests;
- ADR and operational documentation.

## Non-goals

No Voice, MCP, Notification, Memory, Work Graph, automatic retry/compensation, GitHub mutation, live provider cancellation, or new Android behavior enters this branch.
