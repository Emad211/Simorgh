# Phase 1.8 retention and reconciliation candidate

## Base

- Repository: `Emad211/Simorgh`
- Draft PR: #60
- Expected application head: `93ff841295535fefb557df2f7501236ea26f6970`
- Boundary: retention, reconciliation, lifespan/store-path integration and related tests.

## Added

- deterministic source-authority reconciler;
- one request terminal event across specialist retry attempts, controlled by the latest retained attempt;
- zero usage on result-commit trace events;
- typed missing-task/routing/context/invocation/result/parent gaps;
- fail-closed source-evolution gap when retry or terminal task state appears after an immutable request terminal;
- stable terminal source binding to immutable task fingerprint;
- safe operation/failure/reason identifiers;
- retention selector and retention-aware wrapper;
- whole-trace deletion in memory and SQLite;
- protection from nonterminal task/invocation authority, with an immediate pre-delete recheck;
- SQLite restart retention tests;
- trace registry candidate validation before replacement;
- independent trace settings and path-alias gate;
- Core lifespan open → reconcile → wrap → prune → publish order;
- operational guide and ADR 0021.

## Local bundle validation

The transfer bundle itself is checked by:

- exact-head and clean-worktree preconditions;
- exact text-anchor count for every modified file;
- refusal to overwrite an existing new file;
- Python AST parse of Core source and tests;
- `git diff --check`;
- a synthetic application fixture proving all patch anchors and final lifespan nesting;
- focused local tests of reconciliation, replay, usage de-duplication, retry causality, gaps, retention and registry failure behavior.

These checks are transfer validation, not a substitute for repository CI.

## Published clean candidate

- clean product commit: `90e684d41dabec96b355aaa71002f33f6fc370b1`;
- direct parent: `93ff841295535fefb557df2f7501236ea26f6970`;
- product diff: exactly 17 reviewed files;
- temporary `.phase18` transfer files and temporary workflow changes are absent;
- candidate validation run: `30495189320`;
- candidate Core gates: Ruff, strict MyPy and complete pytest passed;
- tested product artifact: `8741297344`;
- artifact digest: `sha256:f6925808d66124bae5d751ece3eece242284eca53875f7c7edae9744e05b4a00`;
- artifact-internal file list, patch and tarball SHA-256 checks passed.

This record triggers the standard repository CI on the actual PR head. Phase 1.8 remains Draft.

## Required repository validation before merge

Run on the exact resulting PR head:

```text
ruff check .
mypy services/core/src
pytest
Android build
Android JVM tests
Android lint
Debug APK upload
```

Also verify:

- no temporary Phase 1.8 workflow or generated `.simorgh` file;
- no unresolved review thread;
- no live model/provider/connector/MCP call in ordinary CI;
- trace database path is distinct from every other durable store;
- restart reconstruction is byte/identity stable;
- Phase 1.8 remains Draft until producer wiring and complete acceptance are finished.

## Remaining Phase 1.8 scope

- direct typed producer integration;
- model/tool and cancellation correlation;
- typed live terminal supersession/resolution events;
- complete deterministic vertical-slice acceptance through real runtime composition;
- final operations/backup incident drills;
- exact-head CI artifacts and review audit;
- merge and Phase 1.9 activation.
