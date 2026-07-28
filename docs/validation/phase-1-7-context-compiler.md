# Phase 1.7 Context Compiler — validation record

## Scope

- Tracking issue: #55.
- Implementation PR: #56.
- Authority boundary: deterministic, bounded, taint-aware specialist context compilation.
- Base authority: merged Phase 1.6 cancellation propagation at `8fd7cb31275d037cb50a4da0ad86c7871f1be13f`.
- Explicitly excluded: model-generated compaction, live embeddings, permanent Memory, Personal Work Graph, final GitHub report execution/presentation, complete trace overhaul, live staging, mutation, Voice, Notification, MCP and new Android behavior.

## Delivered authority

Phase 1.7 now provides:

- strict immutable context request, material, section, schema, budget, omission and bundle contracts;
- structural separation of trusted authority from tainted user and external evidence data;
- exact task, routing, specialist, capability, tool and output-schema intersection;
- typed GitHub evidence conversion preserving source hash, freshness, cache, privacy, citation and taint metadata;
- reviewed projections for `github.search`, `github.fetch-file`, `github.fetch-issue` and `github.fetch-pr`;
- schema-only `simorgh.repository-report.v1` authority for Context Compiler use without adding the Phase 1.10 executor, terminalizer or presentation surface;
- deterministic source and tool-schema ordering, UTF-8-safe compaction, typed omissions and explicit truncation reasons;
- distinct project/goal, decision and evidence limits with priority-based deterministic admission;
- conservative freshness, privacy and retention composition;
- high-confidence concrete credential-shaped material rejection without value echo;
- canonical SHA-256 and UUID5 identity excluding non-authoritative wall-clock/replay fields;
- immutable in-memory and SQLite WAL replay, conflict detection, schema/hash/index integrity, process locking and fail-closed health behavior;
- bounded terminal-history retention that protects contexts referenced by non-terminal specialist invocations;
- cancellation/deadline/fence checks before input authority, after admission before canonical assembly, before durable claim and before handoff;
- privacy-safe `context_compiled`, `context_replayed` and `context_failed` trace metadata;
- independent Core lifespan configuration through `SIMORGH_CONTEXT_STORE_PATH` and `SIMORGH_CONTEXT_STORE_MAX_TERMINAL_RECORDS`;
- `.simorgh/` runtime databases and lock files excluded from version control.

## Required `github.read` vertical slice

The acceptance test proves one durable routed `github.read` task can compile a context from:

- typed public GitHub file evidence;
- the exact `github.fetch-file` reviewed tool schema;
- the explicit context-visible `simorgh.repository-report.v1` output schema;
- remaining budget, deadline and cancellation authority.

The resulting bundle preserves taint, source identity and canonical hashes, replays with the same bundle ID/hash, creates no invocation or usage reservation, leaves task accounting unchanged and supplies the exact context ID/fingerprint to `SpecialistExecutionRequest`.

The global Phase 1.4 authoritative result terminalizer remains typed-plan-only. Complete repository-report execution and Persian presentation remain Phase 1.10.

## Acceptance coverage

Automated tests cover:

- extra/unknown/malformed contracts, schema mismatch and canonical invalid data;
- immutable material registry identity, task ownership and cross-task rejection;
- fake system/role/tool instructions remaining inert tainted data;
- credential-shaped and control-character rejection without value echo;
- tool/connector/capability/output-schema widening rejection;
- source and complete bundle tool-schema permutation determinism;
- policy, budget, source, schema and freshness identity changes;
- exact item/byte/token/text/tool limits;
- project, decision and evidence priority/omission behavior;
- required overflow fail-closed and optional UTF-8-safe truncation reporting;
- stale required rejection, optional stale omission and unknown-freshness rules;
- strictest privacy/retention and taint preservation through replay;
- cancellation before load, after admission before canonical assembly, before commit and before handoff;
- no usage reservation, model/tool/connector/specialist call or automatic retry;
- in-memory/SQLite replay parity, restart replay, conflict, corruption, unsupported schema, process lock and path separation;
- non-terminal retention protection and bounded terminal pruning;
- trace/failure metadata redaction;
- unchanged Android build, JVM tests, lint and debug APK production.

## Zero-external validation boundary

Ordinary CI uses deterministic local stores, fake typed GitHub projections and reviewed schemas. It makes zero live model, provider, connector, MCP or paid external calls.

## Candidate evidence

- Pre-assembly product candidate: `497a3ffe58dad9f9ec52993036b63aa928624924`.
- Its preceding exact product head `7c9e5b60ef84464e12e15c91355920d587bad802` passed CI run `30357147500` with Ruff, strict MyPy, **402 Core tests** and full Android build/JVM/lint/debug-APK gates.
- `497a3ffe58dad9f9ec52993036b63aa928624924` added the focused pre-assembly cancellation-fence recheck and removed its temporary publisher.
- Central documentation was synchronized at candidate `3e79fc202b279a083e113f4e84613d215154a889` with no runtime behavior change.
- The final exact-head standard CI and review audit are recorded in the PR body before merge.

## Final gate

Before merge, the final exact PR head must independently pass the standard repository CI with:

- Core installation, Ruff, strict MyPy and all tests;
- Android build, JVM tests, lint and debug APK upload;
- no temporary publisher workflow, trigger or tracked `.simorgh` runtime file;
- no unresolved review thread or pending change request.

The PR body must record the final exact head, workflow run, Core test count and review audit before merge. After merge, the master-plan closeout records the merge SHA and activates Phase 1.8.

- A focused deadline-race regression proves expiry after canonical assembly is re-evaluated with the current clock before durable claim; no context row is committed when the deadline wins.
