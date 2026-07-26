# Phase 1.4 typed results and artifacts validation candidate

This document records the merge-candidate validation boundary for issue #46 and PR #47.

## Candidate identity

```text
branch: core/typed-results-artifacts
candidate before this validation commit: 4390fabcee9dca766ad16340f385dd5d53a333f7
base authority: main after merged Phase 1.3 PR #44 and closeout PR #45
```

The validation commit that adds this document must receive its own exact-head CI result before merge.

## Implemented trust boundary

- exact result-schema registry with the initial `simorgh.typed-plan.v1@1.0` contract;
- immutable result and producer identities;
- canonical payload/result SHA-256 validation;
- invocation usage and invocation-result hash linkage without copying usage authority;
- typed artifact/evidence metadata;
- privacy composition and retention metadata;
- in-memory exact replay and conflict semantics;
- SQLite WAL result/artifact store with exclusive path ownership;
- artifact byte registration, size and SHA-256 validation;
- completed specialist-invocation terminalization;
- internal status and deterministic Persian rendering;
- process-local trace containing only IDs, hashes, classifications, dispositions and counts;
- no public result-write API and no client-selected result schema or permissions.

## Automated evidence already produced

The protected product finalizers ran:

```text
Ruff: passed
strict MyPy: passed
Core tests after result-store slice: 313 passed
Core tests after invocation-hash reconciliation: 314 passed
```

Multiple exact-head ordinary CI runs during development also kept Android build, JVM tests, lint and debug APK green. These earlier runs are supporting evidence only; the final validation commit still requires its own exact-head CI.

## Required final CI

The exact validation head must pass:

```text
Core install
Core Ruff
strict MyPy
full Core pytest
Android assembleDebug
Android JVM unit tests
Android lintDebug
Debug APK artifact
```

Ordinary CI must use fake/local typed results, evidence and artifact bytes only. It must not call AvalAI, GitHub, Gmail, Calendar, Drive, MCP or another live/paid service.

## Review and scope gate

Before merge:

- no unresolved review thread;
- ADR 0017 remains accepted and matches implementation;
- `docs/RESULT_AUTHORITY.md` matches store/replay/incident behavior;
- PR contains no temporary publisher or diagnostic workflow;
- no live connector, mutation executor, Android side effect, Voice, Notification, Memory, Work Graph, Delegation or retry scope;
- PR body reflects the completed implementation rather than the initial contract slice.

## Physical validation boundary

This is a Core-only authority increment. It does not claim physical Samsung Galaxy A53 validation and does not change Android runtime behavior.
