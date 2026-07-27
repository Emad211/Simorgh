# ADR 0020: Deterministic taint-aware specialist context authority

- Status: Accepted by Phase 1.7 implementation; merge evidence pending PR #56 final gate
- Date: 2026-07-27

## Context

Simorgh already had durable tasks, invocations, specialist execution, typed results/evidence, governed GitHub reads and durable cancellation. Specialist execution contracts already carried `context_bundle_id` and `context_fingerprint`, but no native authority produced or persisted that context. Passing full conversations, raw connector payloads or ad-hoc prompt strings would blur instructions and data, permit prompt-injection authority widening, make replay non-deterministic and hide budget/freshness/privacy decisions.

A Context Compiler must remain earlier than complete trace, live staging and the final GitHub specialist workflow. It therefore cannot depend on model summarization, embeddings, dynamic tool discovery, live connectors, permanent Memory or a final repository report schema that belongs to Phase 1.10.

## Decision

Introduce one Core-owned Context Compiler with strict versioned contracts and a separate immutable SQLite WAL authority.

The bundle contains top-level machine authority for:

- durable task, routing and specialist policy fingerprints;
- exact capability subset;
- typed remaining budget projection;
- reviewed tool-schema projections;
- exact registered output/result schema;
- limits, deadline and freshness class;
- admitted typed data sections and explicit omissions;
- privacy, retention, taint and source-manifest hashes.

Text sections cannot carry policy, schema, budget or permission authority. User input and external evidence have fixed untrusted trust classes and must remain tainted. Approved project facts are trusted data, not system instructions.

Every non-task material must be an exact value in an immutable `ContextMaterialRegistry`, include its owning task `request_id` and match a native source builder or approved project/decision authority. Unknown, changed, duplicate or cross-task material fails closed.

The GitHub source builder accepts only a validated typed projection envelope and preserves projection hash, freshness, cache, privacy and citation metadata while marking content untrusted and tainted.

The compiler performs deterministic local ordering, filtering and prefix compaction. Required sections are never truncated. Optional sections may be truncated or omitted only with typed disposition/reason. Model-generated compaction and live relevance ranking are not part of this decision.

Canonical identity excludes wall-clock and replay presentation fields:

```text
canonical_sha256 = SHA-256(canonical authoritative payload)
context_bundle_id = UUID5("simorgh-context:{request_id}:{canonical_sha256}")
```

One immutable context is permitted per specialist invocation. Exact claims replay; changed context conflicts. SQLite validates schema, row metadata, payload hash, database integrity and exclusive process ownership.

Task cancellation/deadline/fence authority is checked before compilation, before durable claim and after claim before handoff. A bundle committed before a racing cancellation remains immutable, but cancellation blocks specialist handoff.

Context compilation creates no invocation, reservation, committed usage, model call, tool call, connector call or specialist call.

## Consequences

- `SpecialistExecutionRequest.context_bundle_id` and `context_fingerprint` now refer to a real durable native authority.
- Prompt-injection text can remain useful evidence without becoming instructions or permissions.
- Identical authoritative inputs replay byte-identically after restart.
- Policy, budget, schema, material, freshness or capability changes create new context identity.
- Context databases are independent from task, invocation, result and Android journals.
- Failures are visible without leaking task/evidence content.
- `github.read` cannot compile a final repository-report context until `simorgh.repository-report.v1` is registered in the later complete workflow boundary; this is an intentional fail-closed result.
- Context compilation remains zero-external and suitable for deterministic ordinary CI.

## Rejected alternatives

- Pass the complete conversation or project history directly to the specialist.
- Treat delimiters or prose warnings as sufficient prompt-injection protection.
- Let callers submit arbitrary context text as approved evidence.
- Trust a material by ID while ignoring changed content, privacy or task ownership.
- Let a model choose tools, output schemas, permissions or budget during prompt assembly.
- Use embeddings/model summarization in the mandatory compilation path.
- Store context in the result or invocation database without distinct ownership.
- Silently truncate required authority or stale evidence.
- Treat unknown freshness as current.
- Create the final GitHub repository-report schema before Phase 1.10.
- Add a public execution endpoint, Memory, Work Graph, Voice, MCP or Android action in this PR.

## Operational rules

- The compiler policy has an explicit disable switch.
- Required authority overflow, stale required evidence and unknown output schema fail closed.
- Optional exclusions appear in the omission report.
- Private body text never enters traces, failure metadata or status projections.
- Store corruption, unsupported schema or process-lock conflict aborts startup.
- A cancelled task or cancellation fence cannot produce or hand off a new context.
- Existing bundles are immutable audit authority and are never edited in place.

## Follow-up

Phase 1.8 completes end-to-end correlated non-secret tracing. Phase 1.9 validates live providers/connectors under explicit staging budgets. Phase 1.10 registers and executes the complete Persian GitHub repository-report workflow. Voice, Notification, MCP, Memory and Work Graph remain parked until the required Phase 1 sequence is complete.
