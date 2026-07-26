# ADR 0017: Typed result, evidence and artifact authority

- Status: Accepted
- Date: 2026-07-26
- Governing directive: `docs/SIMORGH_MASTER_DIRECTIVE.md`
- Parent implementation issue: #36
- Step issue: #46
- Implementation PR: #47

## Context

ADR 0014 made routed task identity durable. ADR 0015 made individual model, tool and specialist invocation identity, usage reservation, uncertainty and replay durable. ADR 0016 introduced a native specialist execution authority and a concrete typed-plan output.

A completed specialist invocation is still operational execution state. It is not by itself a complete long-lived result authority because later product surfaces need independently addressable:

- typed result schema identity;
- immutable result hash;
- artifact and evidence references;
- privacy and retention metadata;
- deterministic presentation outside authority fields;
- one stable result per completed specialist invocation.

Persisting arbitrary model text, connector output or a user-facing Persian rendering as the authoritative result would make verification, replay, privacy and future artifact handling unreliable.

## Decision

Simorgh introduces a separate typed result authority after successful specialist invocation completion.

```text
TaskStore
    durable task and route

InvocationStore
    execution identity, usage and terminal result payload

ResultStore
    immutable typed result, evidence/artifact metadata,
    privacy, retention and presentation-independent identity
```

The stores are related by stable IDs and hashes but do not duplicate authority.

## Exact schema registry

Every result payload must be validated through an immutable registry key:

```text
(output_contract, result_schema_version)
```

The initial registration is:

```text
simorgh.typed-plan.v1 @ 1.0
    → SpecialistPlanPayload
```

Unknown, duplicate or mismatched contracts fail closed. A new result family requires a separately reviewed typed model and registry entry.

## Result identity and hashing

`SpecialistResultRecord` binds:

- stable result UUID;
- producer request, invocation, agent and version;
- exact output contract and schema version;
- typed payload and payload SHA-256;
- artifact and evidence references;
- unresolved risks and verification requirements;
- privacy and retention classes;
- creation and completion times;
- invocation usage SHA-256;
- invocation result SHA-256;
- canonical result SHA-256.

The result UUID is deterministic for the producing invocation and output contract. Exact replay returns the same record. Reusing the result or invocation identity with different content is a conflict.

## No duplicate cost authority

`InvocationStore.committed_usage` remains the only detailed cost/usage authority.

`ResultStore` does not copy the usage vector. It stores only:

```text
invocation_usage_sha256
```

This proves linkage without creating two mutable accounting truths.

## Terminalization boundary

Only a completed `InvocationKind.SPECIALIST` record can produce a result.

Before writing, Core revalidates:

- request and invocation identity;
- agent ID and exact version;
- completed specialist outcome;
- typed result schema;
- incoming result content against the result stored in `InvocationStore`;
- committed usage through its canonical hash;
- producer identity of every artifact;
- evidence-to-artifact references;
- privacy composition.

The user, model, connector or renderer cannot choose a different schema, producer, permission or hash.

## Artifact boundary

Artifacts are referenced through typed metadata containing ID, SHA-256, media type, size, producer, privacy, retention, storage disposition and optional encryption key reference.

For bounded Core-local bytes, SQLite commits the result and bytes in one transaction only after validating declared size and SHA-256. Unknown artifact IDs and byte mismatches fail before commit.

External-private and public storage are metadata dispositions only in this increment. No external storage adapter is activated.

## Evidence boundary

Evidence references contain source/tool/connector identity, retrieval time, freshness, cache disposition, taint, projection hash, bounded citation reference, optional artifact link and privacy class.

Raw source bodies are not stored in evidence metadata. A result cannot reference an artifact outside itself.

## Privacy and retention

Privacy classes are ordered and compositional:

```text
public < internal < private < sensitive < restricted
```

A parent result must be at least as restrictive as every linked artifact and evidence item.

Retention is recorded as typed policy metadata:

```text
transient | session | project | long_lived | legal_hold
```

Deletion scheduling, legal-hold orchestration and user export/delete UI remain later work.

## Durable store

`SQLiteResultStore` uses WAL, FULL synchronization, foreign keys, a bounded busy timeout and the repository's exclusive process-path lock.

Startup validates:

- SQLite integrity;
- schema version;
- canonical JSON and hashes;
- typed result records;
- result/invocation uniqueness;
- artifact metadata.

Corruption, unsupported schema and multi-process path ownership fail closed. There is no silent in-memory fallback.

## Presentation separation

Persian rendering is deterministic and outside authority fields. The renderer receives a stored result and returns bounded presentation text linked to the same result hash.

Presentation cannot edit payload, evidence, artifacts, privacy, retention or hashes. Unsupported locale fails rather than silently changing language.

## Internal control plane and trace

The initial control plane is Core-internal. It provides terminalize, status lookup, invocation lookup and deterministic render methods without accepting client-selected schemas or permissions.

Status and trace surfaces contain IDs, hashes, contract/schema identity, classification, retention and counts only. They exclude result text, steps, evidence contents and artifact bytes.

Durable end-to-end trace remains Phase 1 Step 1.8.

## Consequences

### Positive

- completed work has a stable typed identity distinct from execution state;
- result replay does not repeat specialist, model or tool work;
- artifacts and evidence are referentially and cryptographically linked;
- privacy cannot be silently downgraded;
- Persian presentation can evolve without changing authority;
- future read-only GitHub evidence can enter through typed metadata and artifacts;
- Usage remains single-authority in `InvocationStore`.

### Negative

- the initial schema registry supports only plan results;
- an additional SQLite store and backup surface exist;
- result retention enforcement is metadata-only;
- artifact bytes currently support only bounded Core-local persistence;
- no public API or application-lifespan production configuration is added here.

## Rejected alternatives

### Treat the invocation result payload as the final product result

Rejected because invocation state lacks independent artifact/evidence, privacy, retention and presentation contracts.

### Persist rendered Persian text as authority

Rejected because localization and formatting would become part of the immutable result identity.

### Persist arbitrary JSON or model output

Rejected because an output-contract label without a concrete typed schema does not provide authority.

### Copy committed usage into the result record

Rejected because that would create a second accounting authority. The result stores a canonical usage hash reference instead.

### Store raw evidence bodies in trace or result metadata

Rejected because provenance metadata and content storage have different privacy and retention requirements.

### Add a live connector or artifact cloud provider in the same PR

Rejected because evidence acquisition and external storage are separate trust boundaries.

## Validation requirements

Before merge, the exact PR head must prove:

- strict result/schema validation and duplicate rejection;
- stable result ID, payload hash and result hash;
- immutable one-result-per-invocation replay;
- invocation content and usage-hash linkage;
- artifact producer, size and SHA-256 validation;
- evidence reference and privacy composition;
- SQLite WAL reopen and exact replay;
- corruption and unsupported-schema failure;
- control-plane status without payload;
- renderer identity preservation;
- private marker absence from traces and failures;
- Core Ruff, strict MyPy and full tests;
- Android build, JVM tests, lint and debug APK;
- no live provider, connector or MCP call;
- no unresolved review thread.

## Follow-up

1. Step 1.5 introduces governed read-only tool execution and one GitHub evidence workflow.
2. Step 1.6 completes task-to-child cancellation propagation.
3. Step 1.7 adds bounded context compilation.
4. Step 1.8 adds durable end-to-end trace.
5. Retention enforcement, user export/delete and external artifact storage require separate reviewed increments.
