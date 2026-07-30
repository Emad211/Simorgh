# Phase 1.8 durable correlated trace — merge closeout

## Status

- Phase: 1.8.
- State: complete.
- Tracking issue: #59 — closed as completed.
- Implementation PR: #60 — merged.
- Exact implementation head: `9060e2541d06b250e6f707885ac541a3b718c31f`.
- Final standard CI run: `30508906505`.
- Merge commit on `main`: `c175dbba8259d12cae1611ed95702e351b8a4636`.
- ADR: 0021 — accepted.

## Final gate evidence

- Core installation: passed.
- Ruff: passed.
- strict MyPy: passed.
- Core tests: 482 passed, 0 failures, 0 errors, 0 skipped.
- Android build: passed.
- Android JVM tests: passed.
- Android lint: passed.
- Debug APK upload: passed.
- Debug APK artifact: `8746362969`, digest `sha256:e13ec21cea9471dac934b10a3248acab0239e6f524736c0078edcccad7651b12`.
- Android diagnostics artifact: `8746362600`, digest `sha256:f2708878f59249c07aa58f6ff7058e5d796171582bfdedaeb24f2b55ac43f61d`.
- Core JUnit artifact: `8746354460`, digest `sha256:6aaa7333b94ad6c7106c42f504fea180c5867925b2ce6e1b3ec9f611b11ab805`.
- Core diagnostics artifact: `8746354275`, digest `sha256:68759fbfe58a62a76ff912eae2b5e7be74b04c9a664d20ff4a82ff779615f23b`.
- Review threads: zero.
- Submitted reviews requiring action: zero.
- PR comments requiring action: zero.
- Final diff contained no temporary workflow, patcher, generated `.simorgh` database, WAL/SHM file or lock file.
- Ordinary CI made zero live model, provider, connector, MCP or paid external calls.

## Delivered authority

Phase 1.8 merged:

- strict versioned trace/event/detail/envelope contracts;
- stable request and source-derived event identities;
- canonical hashes independent of observation/ingestion time;
- transactional per-request sequence and causal validation;
- in-memory and SQLite WAL authorities with replay, conflict, corruption, schema and process-lock semantics;
- direct producer projection after durable task/invocation/context/result commits;
- deterministic zero-external startup reconciliation;
- classifier and specialist-owned model/tool correlation from exact retained identities;
- typed cancellation settlement and conservative unknown-side-effect behavior;
- typed terminal supersession/resolution without rewriting historical events;
- whole-trace retention with active routed-request protection and immediate pre-delete recheck;
- independent path, lifespan ownership, online backup, standalone restore and incident procedures;
- deterministic runtime acceptance using the budgeted classifier, governed GitHub read service, Context Compiler, specialist ownership, replay and SQLite reopen;
- privacy acceptance proving task, classifier and GitHub body markers remain absent from durable Trace.

Trace remains audit projection only. It cannot authorize execution, mutate source authority, synthesize completion, hide uncertainty or trigger retry.

## Next boundary

Phase 1.9 is active in issue #65: explicitly budgeted AvalAI live-provider staging.

The next step may validate at most one manually approved fixed canary call through the existing BudgetedModelGateway and durable authorities, then reconcile its provider request ID through a bounded typed User API lookup. Ordinary CI remains fake/local and zero-external.

Voice, Notification, Scheduling, Channels, Delegation, MCP, Memory, Personal Work Graph, self-improvement, production live-model enablement and the complete GitHub report workflow remain out of scope.
