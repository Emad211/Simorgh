# Simorgh typed result and artifact authority

Status: Phase 1 Step 1.4 implementation in issue #46 and Draft PR #47.

This authority converts one completed, durable specialist invocation into an immutable, versioned result record. It separates operational truth from user-facing presentation and does not add a live connector, model call, MCP server, mutation executor or Android side effect.

## Authority flow

```text
completed InvocationStore(kind=specialist)
    + typed SpecialistExecutionResult
    + Core-selected privacy / retention
    + approved artifact and evidence metadata
        ↓
SpecialistResultAuthorityService
        ↓
ResultSchemaRegistry exact contract/version validation
        ↓
SpecialistResultRecord
        ↓
InMemoryResultStore or SQLiteResultStore
        ↓
internal status / deterministic Persian renderer
```

Clients do not submit a free-form result schema, permissions, storage policy, hash, producer identity or usage total.

## Result identity

The initial result family is:

```text
output contract: simorgh.typed-plan.v1
schema version:  1.0
payload:         SpecialistPlanPayload
```

One result is identified by a stable UUID derived from the producing specialist invocation and exact output contract. The immutable result hash covers:

- producer request, invocation, agent and version;
- output contract and result schema version;
- typed payload and payload SHA-256;
- artifact and evidence metadata;
- unresolved risks and verification requirements;
- invocation usage SHA-256 reference;
- invocation result SHA-256 reference;
- privacy and retention classes;
- creation and completion chronology.

The detailed usage vector remains authoritative only in `InvocationStore`. The result record stores `invocation_usage_sha256` instead of copying usage and creating a second accounting authority.

## Typed payload boundary

`SpecialistPlanPayload` contains bounded fields:

```text
summary
steps
unresolved_risks
verification_requirements
```

Arbitrary dictionaries, raw model strings, connector responses and unrestricted JSON are not accepted as an authoritative result. New result families require a new exact registry entry and independently reviewed typed contract.

Inline payloads are limited to 256,000 canonical JSON bytes.

## Artifacts

`ArtifactReference` records metadata only:

- artifact UUID;
- SHA-256;
- media type;
- byte size;
- producer identity;
- privacy and retention;
- storage disposition and storage reference;
- creation time;
- encryption flag and Core-side key reference.

Storage dispositions are:

```text
core_local
external_private
public
```

A non-public artifact cannot use public storage. An encrypted artifact requires a key reference; an unencrypted artifact cannot carry one.

`SQLiteResultStore.put_with_artifacts()` may persist bounded Core-local bytes. Before the transaction commits it verifies:

```text
registered artifact ID
storage disposition = core_local
actual byte length = declared size
SHA-256(actual bytes) = declared SHA-256
```

Unknown, mismatched or unregistered bytes fail before any result is committed.

## Evidence

`EvidenceReference` stores provenance metadata, not raw source content:

- source identity;
- optional connector and tool identity;
- retrieval time;
- freshness;
- cache disposition;
- taint status;
- projection SHA-256;
- bounded citation reference;
- optional artifact link;
- privacy class.

Evidence cannot point to an artifact outside the same result. Duplicate evidence or artifact IDs are rejected.

## Privacy and retention

Privacy classes are ordered:

```text
public < internal < private < sensitive < restricted
```

The parent result privacy must be at least as restrictive as every linked artifact and evidence reference. Privacy cannot be downgraded during composition.

Retention classes are:

```text
transient
session
project
long_lived
legal_hold
```

This increment records retention policy metadata. Automated deletion, legal-hold orchestration and user export/delete UI remain later retention work.

## Durable store

`SQLiteResultStore` uses:

```text
journal_mode = WAL
synchronous = FULL
foreign_keys = ON
busy_timeout = 5000 ms
exclusive process lock per database path
```

Tables:

```text
result_store_meta
result_records
result_artifacts
```

Startup verifies the SQLite integrity check, supported schema version, every result payload hash and every typed result contract. Corruption, unsupported schema, path-lock failure or unhealthy-store state fails closed.

Exact result replay requires identical immutable content. Reusing a result ID or producer invocation with different content raises a conflict. Replaying the same result returns the original record without changing identity or creating a second result.

## Terminalization from Phase 1.3

`SpecialistResultAuthorityService` accepts only:

- `InvocationKind.SPECIALIST`;
- terminal phase `completed`;
- a durable typed invocation result payload;
- a completed `SpecialistExecutionResult`;
- exact request, invocation, agent, version and content identity;
- exact committed-usage identity through the invocation usage hash.

The incoming specialist result is compared with the result stored in the invocation ledger after normalizing replay disposition. Changed payload, changed producer identity, non-completed invocation or invalid typed result fails before the result store is called.

## Internal control plane

`ResultAuthorityControlPlane` exposes Core-internal methods only:

```text
terminalize(...)
get_status(result_id)
get_status_for_invocation(invocation_id)
render(result_id, locale="fa-IR")
```

Status output intentionally excludes the payload and artifact bytes. It contains IDs, contracts, hashes, classification, retention, counts and timestamps only.

The deterministic Persian renderer is outside authority fields. Rendering cannot change the stored result hash. Unsupported locale does not silently fall back.

No public autonomous result-write endpoint is introduced in this step.

## Trace boundary

Result trace events may contain:

- request, invocation and result IDs;
- agent/version;
- result, payload and invocation-reference hashes;
- contract/schema identity;
- privacy and retention;
- artifact/evidence counts;
- created/replayed/rendered disposition.

They do not contain:

- result summary or steps;
- unresolved-risk text;
- verification text;
- artifact bytes;
- raw evidence or citations;
- prompt, context packet, credentials or connector payloads.

Traces remain bounded and process-local. Durable end-to-end trace remains Phase 1 Step 1.8.

## Backup and incident response

Before copying a live file-backed store, stop the owning Core process or use a SQLite-aware backup procedure that includes WAL state.

On integrity, schema or hash failure:

1. stop ResultStore writes and dependent result presentation;
2. preserve the database, WAL, SHM and lock diagnostics;
3. do not delete or rewrite the failing record;
4. recover from a verified backup or rebuild from authoritative completed invocation records through an explicitly reviewed repair tool;
5. rerun typed validation and hash verification before reopening the store.

There is no `ignore_corruption` mode and no silent fallback to an in-memory authority.

## Current limitations

- only the typed plan result family is registered;
- artifact bytes are supported only for bounded Core-local SQLite storage in this increment;
- external private artifact adapters are metadata-only;
- evidence retrieval is not implemented here;
- the public API remains routing-only;
- no live GitHub, Gmail, Calendar, Drive, browser, shell or MCP tool is called;
- no mutation executor or Android operation is added;
- no automatic retention deletion or user export/delete UI exists;
- result-store path configuration is not yet exposed as a production deployment setting;
- physical Galaxy A53 testing is unrelated to this Core-only trust boundary.

## Validation checklist

Before merge, verify on the exact PR head:

- strict schema and payload validation;
- exact schema registry and duplicate rejection;
- stable result ID and hashes;
- one result per specialist invocation;
- in-memory exact replay and conflict behavior;
- SQLite WAL reopen replay;
- corruption and unsupported-schema failure;
- artifact byte registration, size and SHA-256 enforcement;
- terminalization identity matching;
- status output without payload;
- Persian rendering without authority mutation;
- private marker absent from traces;
- Core Ruff, strict MyPy and full tests;
- Android build, JVM tests, lint and debug APK;
- no live external or paid call in ordinary CI;
- no unresolved review thread.
