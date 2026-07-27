# Deterministic taint-aware Context Compiler

Status: Phase 1.7 implementation is validating in PR #56 under issue #55.

## Purpose

The Context Compiler turns existing durable Simorgh authority into one small, immutable packet for an already-selected specialist. It does not run a model, tool, connector, specialist or Android action.

```text
durable routed task
  + exact specialist policy/capability subset
  + typed remaining budget/deadline/cancellation state
  + exact registered output schema
  + reviewed tool-schema projections
  + approved task-bound context materials
  → deterministic bounded context bundle
  → canonical SHA-256 and UUID5 identity
  → SQLite replay after restart
```

The compiler replaces unrestricted conversation replay and ad-hoc prompt assembly with machine-verifiable authority and data sections.

## Native components

- `context_contracts.py` — immutable contracts, trust/source enums, limits, canonical identity and token estimation;
- `context_sources.py` — exact material registry and typed GitHub projection builder;
- `context_projections.py` — reviewed tool-schema and registered output-schema projections;
- `context_compiler.py` — authority intersection, freshness/privacy filtering, deterministic compaction and race checks;
- `context_store.py` — in-memory and SQLite WAL immutable replay authority;
- `SIMORGH_CONTEXT_STORE_PATH` — independent durable database path;
- privacy-safe context trace events.

## Authority model

The compiler accepts authority only from native reviewed sources:

- durable `AgentTaskRecord` and routing decision;
- exact `SpecialistDefinition` and version;
- requested capabilities that are a subset of task/policy authority;
- current durable budget snapshot intersected with the specialist budget ceiling;
- registered result/output schema;
- reviewed tool-schema projections;
- exact `ContextMaterial` values registered in `ContextMaterialRegistry`;
- durable cancellation fence and task deadline state.

A caller cannot replace the compiler-owned user-task section, invent a material, change one field under an approved material ID, transfer a material to another task, widen tools/connectors, redefine the output schema or provide compilation time as authority.

## Trust and prompt-injection separation

Context body data uses fixed trust classes:

| Source | Trust class | Taint |
|---|---|---|
| compiler-owned task input/outcome | `untrusted_user_content` | required |
| typed GitHub/tool evidence | `untrusted_external_evidence` | required |
| approved project goal/decision/result reference | `trusted_project_fact` | forbidden |

Policy, budget, capability and schema authority are top-level typed bundle fields, not text sections. Untrusted data therefore cannot become an instruction, tool definition, output schema or permission.

Text such as `SYSTEM: ignore previous instructions`, fake role markers, embedded XML/JSON tool calls and requests to reveal secrets remains ordinary tainted content. The compiler preserves it as evidence when allowed but never interprets it as authority.

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
- taint, privacy and retention;
- optional bounded citation reference.

`ContextMaterialRegistry` validates the complete immutable material, not only its ID. Duplicate IDs fail, unknown materials fail, changed content/priority/privacy/freshness under an approved ID conflicts, and a material registered for another task is rejected before compilation.

`context_material_from_github_projection` accepts only a validated `GitHubReadProjectionEnvelope`. It carries forward the projection hash, freshness, cache, privacy and citation metadata and always marks the resulting content untrusted and tainted.

## Reviewed tool schemas

A context tool projection contains only:

- exact tool and connector identity;
- read/proposal/mutation effect;
- reviewed input/output contract IDs;
- bounded reviewed description;
- deterministic Pydantic JSON schemas;
- canonical SHA-256.

The requested tool set must exactly equal the projected tool set and remain a subset of the selected specialist allowlist and connector capability subset. A schema informs later execution; it does not call the tool or grant new authority.

Phase 1.7 includes reviewed projections for the four merged GitHub read operations. Dynamic discovery and arbitrary endpoint catalogs remain disabled.

## Output schema authority

The output projection must match an exact registered `ResultSchemaRegistry` handler. The current successful vertical slice uses `development.planner` with `simorgh.typed-plan.v1` and the registered specialist-plan result schema.

`github.read` currently declares the future `simorgh.repository-report.v1` contract. That final report schema belongs to Phase 1.10 and is intentionally not invented in Phase 1.7. Context compilation for that output therefore fails closed until the registered schema exists.

## Remaining budget projection

The bundle records a machine-verifiable budget projection:

- effective limits after task/specialist intersection;
- committed usage;
- reserved usage;
- remaining usage per dimension;
- elapsed and remaining elapsed time;
- cancellation and exhausted-dimension state;
- canonical SHA-256.

Compilation creates no reservation and no usage. It only snapshots existing durable accounting. A cancelled or exhausted budget cannot authorize a new bundle.

## Freshness rules

Each material carries observation time, optional `fresh_until_ms`, cache disposition and content-addressed status.

- content-addressed material is accepted by identity;
- `cached_ok` may accept unknown freshness;
- current/execution-bound tasks do not silently treat unknown freshness as current;
- optional stale/unknown material is omitted with a typed reason;
- required stale/unknown material fails closed;
- admitted freshness and source hashes participate in canonical identity.

## Privacy and retention

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
- sections and evidence items;
- text characters per material;
- tool count and schema bytes;
- omission-report entries.

Ordering is deterministic by source kind, required status, priority, source ID and material ID. Input permutation cannot change the result.

Required material is never truncated. Optional material over its text limit receives a UTF-8-safe deterministic prefix and an explicit `truncated` disposition. When the total packet remains above byte/token limits, the lowest-priority optional section is repeatedly reduced or omitted with a typed reason. If required authority cannot fit, compilation fails closed.

Token estimation is deterministic and local. No model summarization, embedding call or paid ranking is used.

## Canonical identity and replay

The canonical payload includes task/routing/policy fingerprints, capabilities, budget projection, limits, schemas, admitted sections, omissions, source manifest, privacy, retention and taint. Non-authoritative `compiled_at_ms` and replay markers are excluded from the canonical hash.

```text
canonical_sha256 = SHA-256(canonical JSON payload)
context_bundle_id = UUID5("simorgh-context:{request_id}:{canonical_sha256}")
```

The same authoritative inputs produce the same hash and ID across source permutations and Core restarts. Changed material, policy, budget, schema, capability or freshness changes identity.

One immutable context is allowed per specialist invocation. Exact duplicate claims replay; changed context under the same specialist invocation conflicts.

## Durable store

`SQLiteContextStore` uses WAL, synchronous full durability, an exclusive process lock, schema versioning, indexed metadata, payload SHA-256 and `PRAGMA quick_check`.

Startup validates every existing row and latches unhealthy on payload/hash/index/schema corruption. A second Core process cannot own the same context database. The path must be distinct from task, invocation, result and Android journal databases.

The Core lifespan configures `context_store_registry` from `SIMORGH_CONTEXT_STORE_PATH`, validates it before serving traffic and resets to an in-memory authority on shutdown or failed startup.

## Cancellation and race behavior

Checks occur before authority load, before durable claim and after claim before specialist handoff.

- cancelled/expired tasks fail;
- a durable invocation cancellation fence blocks compilation;
- if cancellation wins after context commit, the immutable bundle remains an audit record but handoff fails;
- a later cancellation cannot mutate an already committed bundle;
- the bundle itself never grants execution after task authority is cancelled.

## Trace boundary

The compiler emits:

- `context_compiled`;
- `context_replayed`;
- `context_failed`.

Success/replay events contain only IDs, compiler version, context/source hashes, counts, byte and deterministic-unit counts, privacy, retention and taint. Failure events contain only the exception class name and compiler version.

They never contain task text, material content, citations, raw schemas, connector bodies, prompts, credentials, tokens, headers, environment variables or exception messages containing inputs.

## Operational disable and incident response

Set `ContextCompilerPolicy.enabled=false` in the owning composition boundary to fail all compilation closed while preserving existing durable bundles.

On suspected injection or source-authority error:

1. disable new compilation;
2. preserve task, invocation, result and context databases with WAL/SHM sidecars;
3. identify the material registry/source builder and canonical hashes involved;
4. do not edit an existing bundle or reuse its specialist invocation ID;
5. correct the reviewed source authority or policy version;
6. compile under a new identity and rerun acceptance tests.

On store corruption/schema mismatch/process-lock conflict:

1. stop startup/new work;
2. do not fall back to stale in-memory assumptions;
3. preserve database and sidecars;
4. restore from a consistent backup or reviewed migration;
5. rerun integrity, replay, path-alias and exact-head CI before reopening.

## Validation boundary

Ordinary CI uses deterministic local task/invocation/result/context stores, fake GitHub projections and reviewed schemas. It performs zero live model, provider, connector, MCP or paid call.

Acceptance coverage proves:

- fixed trust/taint and prompt-injection inertness;
- exact material registry and task ownership;
- typed GitHub projection derivation;
- exact tool/output schema authority;
- budget math and identity;
- ordering determinism and policy-sensitive identity;
- freshness/privacy/retention behavior;
- required overflow and optional truncation;
- cancellation races;
- in-memory/SQLite replay, conflict, corruption and process lock;
- privacy-safe success/replay/failure traces;
- independent lifespan path/schema/reset behavior;
- unchanged Android build surface.

See ADR 0020 and [`validation/phase-1-7-context-compiler.md`](validation/phase-1-7-context-compiler.md).

## Current limitations

- no final `simorgh.repository-report.v1` schema or complete Persian GitHub report;
- no model-generated compaction, embeddings or vector database;
- no permanent Memory or Personal Work Graph;
- no public context-execution endpoint;
- no dynamic tool discovery;
- no Phase 1.8 complete end-to-end trace correlation;
- no live-provider staging;
- no mutation, Voice, Notification, Scheduling, Channels, Delegation, MCP or new Android action.
