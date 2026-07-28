# ADR 0020: Deterministic taint-aware specialist context authority

- Status: Accepted by Phase 1.7 implementation; merge evidence pending PR #56 final gate
- Date: 2026-07-27

## Context

Simorgh already had durable tasks, invocations, specialist execution, typed
results/evidence, governed GitHub reads, and durable cancellation. Specialist
execution contracts carried `context_bundle_id` and `context_fingerprint`, but
no native authority produced or persisted that context. Passing full
conversations, raw connector payloads, or ad-hoc prompt strings would blur
instructions and data, permit prompt-injection authority widening, make replay
non-deterministic, and hide budget/freshness/privacy decisions.

The Context Compiler must remain earlier than complete trace, live staging, and
the complete GitHub specialist workflow. It cannot depend on model
summarization, embeddings, dynamic discovery, live connectors, permanent
Memory, or a final report executor. It may register the strict output schema
needed to make context machine-verifiable without implementing that later
workflow.

## Decision

Introduce one Core-owned Context Compiler with strict versioned contracts and a
separate immutable SQLite WAL authority.

The bundle contains top-level machine authority for:

- durable task, routing, and specialist policy fingerprints;
- exact capability subset;
- typed remaining budget projection;
- reviewed tool-schema projections;
- exact registered output/result schema;
- limits, deadline, and freshness class;
- admitted typed data sections and explicit omissions;
- privacy, retention, taint, and source-manifest hashes.

Text cannot carry policy, schema, budget, or permission authority. User input
and external evidence have fixed untrusted trust classes and remain tainted.
Approved project facts are trusted data, not system instructions.

Every non-task material must be an exact value in an immutable
`ContextMaterialRegistry`, include its owning task `request_id`, and match a
native source builder or approved project/decision authority. Unknown, changed,
duplicate, or cross-task material fails closed.

The GitHub source builder accepts only a validated typed projection envelope and
preserves projection hash, freshness, cache, privacy, and citation metadata
while marking content untrusted and tainted.

The compiler performs deterministic local ordering, filtering, and UTF-8-safe
prefix compaction. Required sections are never truncated. Optional sections may
be reduced or omitted only with typed disposition and reason. Model-generated
compaction and live relevance ranking are excluded.

Canonical identity excludes wall-clock and replay presentation fields:

```text
canonical_sha256 = SHA-256(canonical authoritative payload)
context_bundle_id = UUID5("simorgh-context:{request_id}:{canonical_sha256}")
```

One immutable context is permitted per specialist invocation. Exact claims
replay; changed context conflicts. SQLite validates schema, row metadata,
payload hash, database integrity, and exclusive process ownership.

Terminal context history is bounded, while contexts owned by non-terminal
specialist invocations are protected from retention pruning.

Task cancellation/deadline/fence authority is checked before compilation,
before durable claim, and after claim before handoff. A bundle committed before
a racing cancellation remains immutable, but cancellation blocks handoff.

Context compilation creates no invocation, reservation, committed usage, model
call, tool call, connector call, specialist call, or Android side effect.

Phase 1.7 registers a strict schema-only `simorgh.repository-report.v1` family
for Context Compiler use. This is sufficient for one routed `github.read`
context to carry an exact expected output schema. It does not add the report
executor, authoritative repository-report terminalizer, model workflow, or
Persian presentation; those remain Phase 1.10.

## Consequences

- `SpecialistExecutionRequest.context_bundle_id` and `context_fingerprint` refer
  to a real durable native authority.
- Prompt-injection text can remain useful evidence without becoming authority.
- Identical authoritative inputs replay byte-identically after restart.
- Policy, budget, schema, material, freshness, or capability changes create a
  new context identity.
- Context databases are independent from task, invocation, result, and Android
  journals.
- Failures are visible without leaking task or evidence content.
- A routed `github.read` task can compile typed GitHub evidence and exact tool
  and repository-report schemas, while execution remains unavailable.
- The global Phase 1.4 result terminalizer remains typed-plan-only; the
  repository-report family is explicitly context-visible through
  `default_context_result_schema_registry()`.
- Context compilation remains zero-external and deterministic in ordinary CI.

## Rejected alternatives

- Pass the complete conversation or project history directly.
- Treat delimiters or prose warnings as prompt-injection protection.
- Let callers submit arbitrary text as approved evidence.
- Trust a material ID while ignoring changed content, privacy, or ownership.
- Let a model choose tools, schemas, permissions, or budget during assembly.
- Use embeddings or model summarization in the mandatory path.
- Store context in result or invocation databases without distinct ownership.
- Silently truncate required authority or stale evidence.
- Treat unknown freshness as current.
- Implement the complete GitHub report executor or presentation in Phase 1.7.
- Add a public execution endpoint, Memory, Work Graph, Voice, MCP, or Android
  action in this PR.

## Operational rules

- The compiler policy has an explicit disable switch.
- Required overflow, stale required evidence, and unknown output schema fail
  closed.
- Optional exclusions and truncations appear in the omission report.
- High-confidence credential-shaped context is rejected without echo.
- Private body text never enters traces, failure metadata, or status views.
- Store corruption, unsupported schema, or process-lock conflict aborts startup.
- A cancelled task or cancellation fence cannot produce or hand off new context.
- Existing bundles are immutable audit authority and never edited in place.
- Runtime `.simorgh` databases and lock files are never tracked in Git.

## Follow-up

Phase 1.8 completes end-to-end correlated non-secret tracing. Phase 1.9
validates live providers/connectors under explicit staging budgets. Phase 1.10
implements the complete Persian GitHub repository-report workflow. Voice,
Notification, MCP, Memory, and Work Graph remain parked until the required
Phase 1 sequence is complete.
