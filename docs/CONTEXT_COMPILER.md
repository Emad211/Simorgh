# Deterministic taint-aware Context Compiler

Status: Phase 1.7 merged through PR #56 at `dab5333140da2d9cf9b982a57ede1a2d08397cf1`; issue #55 completed and ADR 0020 accepted. Phase 1.8 durable correlated Trace merged through PR #60.

## Purpose

The Context Compiler turns existing durable Simorgh authority into one small,
immutable packet for an already-selected specialist. It does not run a model,
tool, connector, specialist, or Android action.

```text
durable routed task
  + exact specialist policy/capability subset
  + typed remaining budget/deadline/cancellation state
  + exact registered output schema
  + reviewed tool-schema projections
  + approved task-bound context materials
  -> deterministic bounded context bundle
  -> canonical SHA-256 and UUID5 identity
  -> SQLite replay after restart
```

The compiler replaces unrestricted conversation replay and ad-hoc prompt
assembly with machine-verifiable authority and data sections.

## Native components

- `context_contracts.py` — immutable contracts, trust/source enums, limits,
  canonical identity, secret-shaped text rejection, and deterministic token
  estimation;
- `context_sources.py` — exact material registry and typed GitHub projection
  builder;
- `context_projections.py` — reviewed tool-schema and registered output-schema
  projections;
- `context_result_schemas.py` — schema-only context authority for output
  families not yet executable by the global result terminalizer;
- `context_compiler.py` — authority intersection, freshness/privacy filtering,
  deterministic admission/compaction, and cancellation race checks;
- `context_store.py` — immutable in-memory and SQLite WAL replay authority;
- `context_retention.py` — bounded terminal-context retention that protects
  nonterminal specialist invocations;
- `SIMORGH_CONTEXT_STORE_PATH` — independent durable database path;
- `SIMORGH_CONTEXT_STORE_MAX_TERMINAL_RECORDS` — retained terminal context
  history;
- privacy-safe context trace events.

Generated `.simorgh/` runtime databases and lock files are ignored by Git.

## Authority model

The compiler accepts authority only from native reviewed sources:

- durable `AgentTaskRecord` and routing decision;
- exact `SpecialistDefinition` and version;
- requested capabilities that are a subset of task/policy authority;
- current durable budget snapshot intersected with the specialist budget
  ceiling;
- registered result/output schema;
- reviewed tool-schema projections;
- exact `ContextMaterial` values registered in `ContextMaterialRegistry`;
- durable cancellation fence and task deadline state.

A caller cannot replace the compiler-owned user-task section, invent a material,
change one field under an approved material ID, transfer a material to another
task, widen tools/connectors, redefine the output schema, or provide compilation
time as authority.

## Trust and prompt-injection separation

Context body data uses fixed trust classes:

| Source | Trust class | Taint |
|---|---|---|
| compiler-owned task input/outcome | `untrusted_user_content` | required |
| typed GitHub/tool evidence | `untrusted_external_evidence` | required |
| approved project goal/decision/result reference | `trusted_project_fact` | forbidden |

Policy, budget, capability, and schema authority are top-level typed bundle
fields, not text sections. Untrusted data therefore cannot become an
instruction, tool definition, output schema, or permission.

Text such as `SYSTEM: ignore previous instructions`, fake role markers,
embedded XML/JSON tool calls, and requests to reveal secrets remains ordinary
tainted content. The compiler preserves it as data when allowed but never
interprets it as authority.

High-confidence credential-shaped material is rejected before compilation:
GitHub token forms, concrete authorization headers, private-key headers, and
bounded key/token/password assignments. Generic words such as `token` remain
ordinary data; concrete secret-like values fail closed without being echoed in
validation errors or traces.

## Task-bound material authority

Every material includes:

- immutable `material_id`;
- owning `request_id`;
- source kind and fixed trust class;
- source and content SHA-256;
- bounded content;
- required/priority fields;
- observation and freshness times;
- cache disposition;
- content-addressed flag;
- taint, privacy, and retention;
- optional bounded citation reference.

`ContextMaterialRegistry` validates the complete immutable material, not only
its ID. Duplicate IDs fail, unknown materials fail, changed
content/priority/privacy/freshness under an approved ID conflicts, and a
material registered for another task is rejected before compilation.

`context_material_from_github_projection` accepts only a validated
`GitHubReadProjectionEnvelope`. It carries forward the projection hash,
freshness, cache, privacy, and citation metadata and always marks the resulting
content untrusted and tainted.

## Reviewed tool schemas

A context tool projection contains only:

- exact tool and connector identity;
- read/proposal/mutation effect;
- reviewed input/output contract IDs;
- bounded reviewed description;
- deterministic Pydantic JSON schemas;
- canonical SHA-256.

The requested tool set must exactly equal the projected tool set and remain a
subset of the selected specialist allowlist and connector capability subset. A
schema informs later execution; it does not call the tool or grant new
authority.

Tool schemas are canonically ordered by tool and connector identity before
hashing and storage. Input permutation therefore cannot change bundle hash,
UUID, replay behavior, or stored order.

Phase 1.7 includes reviewed projections for the four merged GitHub read
operations. Dynamic discovery and arbitrary endpoint catalogs remain disabled.

## Output schema authority

The output projection must match an exact registered `ResultSchemaRegistry`
handler.

Two schema families are available to context compilation:

- `simorgh.typed-plan.v1` through the existing specialist-plan result authority;
- schema-only `simorgh.repository-report.v1` through
  `default_context_result_schema_registry()`.

The repository-report schema lets a routed `github.read` context carry a strict
expected output contract today. It does not add the Phase 1.10 report executor,
authoritative terminalization workflow, model orchestration, or Persian
presentation. The global Phase 1.4 result terminalizer remains typed-plan-only.

## Remaining budget projection

The bundle records a machine-verifiable budget projection:

- effective limits after task/specialist intersection;
- committed usage;
- reserved usage;
- remaining usage per dimension;
- elapsed and remaining elapsed time;
- cancellation and exhausted-dimension state;
- canonical SHA-256.

Compilation creates no reservation and no usage. It only snapshots existing
durable accounting. A cancelled or exhausted budget cannot authorize a new
bundle.

## Freshness rules

Each material carries observation time, optional `fresh_until_ms`, cache
disposition, and content-addressed status.

- content-addressed material is accepted by identity;
- `cached_ok` may accept unknown freshness;
- current/execution-bound tasks do not silently treat unknown freshness as
  current;
- optional stale/unknown material is omitted with a typed reason;
- required stale/unknown material fails closed;
- admitted freshness and source hashes participate in canonical identity.

## Privacy and retention classification

Compiler policy has explicit privacy and retention ceilings.

- optional material above a ceiling is omitted with a typed reason;
- required material above a ceiling fails closed;
- bundle privacy and retention equal the strictest admitted section values;
- taint is true when any admitted section is tainted;
- citations remain bounded metadata;
- body text never enters trace or failure metadata.

## Limits and deterministic compaction

Reviewed limits cover:

- total canonical bytes;
- estimated tokens;
- total sections;
- evidence items;
- project/goal items;
- decision items;
- text characters per material;
- tool count and schema bytes;
- omission-report entries.

Ordering is deterministic by source kind, required status, priority, source ID,
and material ID. Input permutation cannot change the result.

Required material is never truncated. Optional material over its text limit
receives a UTF-8-safe deterministic prefix, a `truncated` disposition, and one
deduplicated typed omission record carrying source identity and `text_limit`.
Byte/token compaction likewise records one typed reason per source/reason pair.
Project, decision, evidence, section, privacy, retention, byte, and token
exclusions are all explicit. If required authority cannot fit, compilation fails
closed.

Token estimation is deterministic and local. No model summarization, embedding
call, or paid ranking is used.

## Canonical identity and replay

The canonical payload includes task/routing/policy fingerprints, capabilities,
budget projection, limits, canonical schemas, admitted sections, omissions,
source manifest, privacy, retention, and taint. Non-authoritative
`compiled_at_ms` and replay markers are excluded from the canonical hash.

```text
canonical_sha256 = SHA-256(canonical JSON payload)
context_bundle_id = UUID5("simorgh-context:{request_id}:{canonical_sha256}")
```

The same authoritative inputs produce the same hash and ID across material and
tool-schema permutations and Core restarts. Changed material, policy, budget,
schema, capability, or freshness changes identity.

One immutable context is allowed per specialist invocation. Exact duplicate
claims replay; changed context under the same specialist invocation conflicts.

## Durable store and bounded retention

`RetentionAwareSQLiteContextStore` wraps the immutable WAL store with bounded
terminal-context retention. `SIMORGH_CONTEXT_STORE_MAX_TERMINAL_RECORDS`
controls how many newest contexts whose specialist invocations are durably
terminal remain stored.

The current claim and every context linked to a nonterminal specialist
invocation are protected. Pruning is deterministic and never uses task age as a
substitute for invocation terminality.

The underlying SQLite authority uses WAL, synchronous full durability, an
exclusive process lock, schema versioning, indexed metadata, payload SHA-256,
and `PRAGMA quick_check`.

Startup validates every existing row and latches unhealthy on
payload/hash/index/schema corruption. A second Core process cannot own the same
context database. The path must be distinct from task, invocation, result, trace,
and Android journal databases.

The Core lifespan configures `context_store_registry`, validates and prunes the
store before serving traffic, and resets to an in-memory authority on shutdown
or failed startup.

## Cancellation and race behavior

Checks occur before authority load, after material admission and before
canonical assembly, before durable claim, and after claim before specialist
handoff.

- cancelled/expired tasks fail;
- a durable invocation cancellation fence blocks compilation;
- cancellation that wins after admission cannot enter canonical assembly or
  durable claim;
- if cancellation wins after context commit, the immutable bundle remains an
  audit record but handoff fails;
- a later cancellation cannot mutate an already committed bundle;
- the bundle itself never grants execution after task authority is cancelled.

## Trace boundary

The compiler emits:

- `context_compiled`;
- `context_replayed`;
- `context_failed`.

Success/replay events contain only IDs, compiler version, context/source hashes,
counts, byte and deterministic-unit counts, privacy, retention, and taint.
Failure events contain only the exception class name and compiler version.

They never contain task text, material content, citations, raw schemas,
connector bodies, prompts, credentials, tokens, headers, environment variables,
or exception messages containing inputs.

## Operational disable and incident response

Set `ContextCompilerPolicy.enabled=false` in the owning composition boundary to
fail all compilation closed while preserving existing durable bundles.

On suspected injection or source-authority error:

1. disable new compilation;
2. preserve task, invocation, result, and context databases with WAL/SHM
   sidecars;
3. identify the material registry/source builder and canonical hashes involved;
4. do not edit an existing bundle or reuse its specialist invocation ID;
5. correct the reviewed source authority or policy version;
6. compile under a new identity and rerun acceptance tests.

On store corruption/schema mismatch/process-lock conflict:

1. stop startup/new work;
2. do not fall back to stale in-memory assumptions;
3. preserve database and sidecars;
4. restore from a consistent backup or reviewed migration;
5. rerun integrity, replay, path-alias, retention, and exact-head CI gates.

## Validation boundary

Ordinary CI uses deterministic local task/invocation/result/context stores,
fake GitHub projections, and reviewed schemas. It performs zero live model,
provider, connector, MCP, or paid call.

Acceptance coverage proves:

- fixed trust/taint and prompt-injection inertness;
- concrete credential rejection without echo;
- exact material registry and task ownership;
- typed GitHub projection derivation;
- routed `github.read` context compilation and zero-cost replay;
- exact tool/output schema authority;
- tool-schema permutation invariance;
- budget math and policy-sensitive identity;
- freshness/privacy/retention behavior;
- independent project/decision/evidence/section ceilings;
- required overflow and optional truncation with typed reasons;
- pre-assembly, pre-claim, and post-claim cancellation races;
- in-memory/SQLite replay, conflict, corruption, process lock, and bounded
  terminal retention;
- privacy-safe success/replay/failure traces;
- independent lifespan path/schema/reset behavior;
- unchanged Android build surface.

See ADR 0020 and
[`validation/phase-1-7-context-compiler.md`](validation/phase-1-7-context-compiler.md).

## Current limitations

- no complete GitHub repository-report executor, terminalizer, or Persian
  presentation;
- no model-generated compaction, embeddings, or vector database;
- no permanent Memory or Personal Work Graph;
- no public context-execution endpoint;
- no dynamic tool discovery;
- no completed live-provider staging;
- no mutation, Voice, Notification, Scheduling, Channels, Delegation, MCP, or
  new Android action.
