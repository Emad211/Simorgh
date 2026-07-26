# Simorgh typed specialist result authority

Status: Phase 1 Step 1.4 is validating in PR #48 under issue #46. ADR 0017 is proposed until exact-head CI and review gates close.

## Purpose

The Phase 1.3 `SpecialistExecutionResult` is the durable execution payload for one specialist invocation. Phase 1.4 creates a separate final result authority for schema identity, artifact/evidence provenance, privacy, retention, canonical replay and localized presentation.

The authority never accepts arbitrary model text, free-form dictionaries, raw connector responses, artifact bytes, credentials or user-facing presentation as an unvalidated final result.

## Authority flow

```text
completed InvocationStore(kind=specialist)
    ↓ exact identity, payload and usage cross-check
ResultSchemaRegistry
    ↓ exact schema ID + version + output contract
AuthoritativeSpecialistResult
    ↓ immutable claim
ResultStore (memory or SQLite WAL)
    ├── canonical typed payload
    ├── artifact references
    ├── evidence references
    ├── uncertainty
    ├── privacy / retention
    └── canonical SHA-256
    ↓
non-authoritative Persian renderer
```

A Phase 1.4 success is not reported until the result store has durably claimed the exact authority record.

## Initial registered family

```text
output contract: simorgh.typed-plan.v1
result schema ID: simorgh.specialist-plan-result
result schema version: 1.0
family: specialist_plan
payload: SpecialistPlanPayload
```

Registry lookup is exact. Duplicate registrations, unknown schema IDs, unknown versions, family mismatches and output-contract mismatches fail closed.

Only this family is registered in the current increment. A later family requires its own typed payload model, registry entry, validation rules, renderer and tests.

## Authoritative result fields

`AuthoritativeSpecialistResult` is frozen and rejects unknown fields. It binds:

- deterministic UUID5 result ID;
- request ID and specialist invocation ID;
- producer agent ID and semantic version;
- output contract, family, schema ID and schema version;
- concrete typed payload;
- ordered artifact and evidence references;
- direct committed-usage invocation identity;
- uncertainty disposition, unresolved risks and verification requirements;
- privacy classification and retention disposition;
- creation and completion timestamps;
- canonical SHA-256;
- fresh or replayed return disposition.

The canonical hash excludes only the hash field itself and the return-only replay disposition. Presentation text is never part of the authority hash.

## Result identity and replay

The stable result ID is derived from:

```text
invocation_id
result_schema_id
result_schema_version
```

One specialist invocation can claim one immutable authoritative result. Reusing the result or invocation identity with different content is a conflict.

Completed replay:

- returns the stored result ID and canonical hash;
- does not execute the specialist again;
- does not reserve or commit new usage;
- does not depend on the current executor registry;
- does not rewrite privacy or retention;
- does not replace artifact or evidence metadata;
- may expose `replay=replayed` in the returned view without changing the stored canonical authority.

## Cross-authority terminalization

`SpecialistResultTerminalizer` loads the invocation authority and verifies:

```text
invocation exists
kind == specialist
state == completed
durable typed payload == supplied execution result
durable committed usage == supplied direct usage
registered schema matches output contract
```

If any check fails, no result is created. If the result store fails after Phase 1.3 completion, the caller receives no Phase 1.4 success; the completed invocation remains available for a later idempotent terminalization attempt.

## Artifact references

The current result store persists artifact metadata, not artifact bytes.

Each `ArtifactReference` contains:

- artifact ID;
- canonical SHA-256 and byte size;
- normalized media type;
- request, invocation and producer identity;
- privacy and retention;
- storage disposition;
- bounded storage reference when applicable;
- creation time and optional expiry;
- optional encryption-key reference.

Storage dispositions:

```text
test_fixture
local_reference
private_reference
public_reference
```

Rules:

- referenced storage requires a bounded reference;
- test fixtures cannot pretend to have a storage location;
- public storage is permitted only for public artifacts;
- legal-hold artifacts cannot expire;
- an expiry must be later than creation;
- artifact producer identity must match the result producer;
- deterministic fake bytes in tests must match declared size and SHA-256.

Production artifact-byte storage, encryption lifecycle, garbage collection and delivery are later trust boundaries.

## Evidence references

`EvidenceReference` is a presentation-neutral projection containing:

- evidence ID;
- source ID;
- optional connector and tool IDs;
- observation and freshness timestamps;
- cache disposition;
- untrusted-source and taint flags;
- projection SHA-256;
- bounded citation reference;
- optional artifact ID;
- privacy classification.

An untrusted source must remain tainted. Evidence cannot reference an artifact outside the same result. Raw source bodies, connector payloads, tool arguments, prompts and private content are excluded.

The first governed GitHub read tools in Phase 1.5 must produce typed evidence projections compatible with this authority rather than persisting raw connector responses.

## Privacy and retention

Privacy classifications, from least to most restrictive:

```text
public
internal
private
sensitive
restricted
```

Retention dispositions, from shortest to strongest:

```text
transient
session
project
long_lived
legal_hold
```

The result effective privacy is the strictest of the requested result policy and all linked artifact/evidence classifications. The result effective retention is at least the longest linked artifact retention.

Replay cannot downgrade or silently strengthen these fields. A requested policy change requires a separately governed migration or new authority identity.

## Uncertainty

The result carries explicit uncertainty independent of presentation:

```text
none
 declared
unverified
```

`none` cannot carry unresolved risks or verification requirements. A non-none disposition must carry at least one bounded risk or verification requirement. For the initial typed-plan family, these fields must exactly match the typed payload.

## Persian rendering

`PersianSpecialistPlanRenderer` produces deterministic Persian text from the stored typed plan. The rendered object contains:

- locale;
- text;
- result ID;
- authoritative result hash;
- `authoritative=false`.

Unsupported locale requests fall back explicitly to `fa-IR`. Rendering is bounded and cannot mutate or rehash the result. A different renderer can be added later without changing result identity.

## Durable stores

### In-memory store

The in-memory implementation is strict and process-local. It is used by isolated tests and safe startup fallbacks.

### SQLite store

The SQLite authority uses:

- a dedicated path configured by `SIMORGH_RESULT_STORE_PATH`;
- a non-blocking process-ownership lock;
- WAL mode for file-backed databases;
- `synchronous=FULL`;
- schema version `1`;
- canonical payload JSON and payload SHA-256;
- immutable `result_id` primary key;
- unique `invocation_id`;
- indexed-column versus payload identity checks;
- `PRAGMA integrity_check` on startup/load;
- corruption latching and fail-closed subsequent access.

The result path must not alias the task store, invocation store or Android action journal, including hard-link aliases.

## Startup and shutdown

Core lifespan order is deliberate:

```text
open/recover invocation authority
open/verify result authority
open Android action journal and task authority
reconcile task usage from invocations
configure process registries
```

If any startup stage fails, already-open authorities are closed or reset. Shutdown resets the result registry before the invocation registry.

## Trace boundary

Result trace kinds:

```text
result_committed
result_replayed
result_failed
```

Trace metadata may include only bounded identifiers and classifications such as result/schema IDs, canonical hash, reference counts, privacy, retention and replay state.

It never includes:

- typed payload content;
- rendered Persian text;
- evidence body;
- artifact bytes;
- storage credentials;
- prompt/context body;
- connector response;
- tool arguments or results.

## Failure behavior

| Failure | Behavior |
|---|---|
| Unknown schema/version | Reject before result claim |
| Duplicate schema registration | Startup/construction failure |
| Invocation missing/not specialist/not completed | Reject terminalization |
| Durable payload or usage mismatch | Reject; no result |
| Result identity reused with changed content | Conflict |
| Replay supplies changed references | Conflict |
| Artifact size/hash mismatch | Reject |
| Non-public artifact points to public storage | Reject |
| Evidence freshness precedes observation | Reject |
| Untrusted evidence loses taint | Reject |
| Payload hash or indexed columns corrupted | Latch store unhealthy |
| Unsupported SQLite schema | Abort startup |
| Concurrent process owns store | Fail startup without sharing authority |
| Renderer exceeds bound | Reject presentation only; authority unchanged |

## Backup and incident handling

The result database contains operational result metadata and typed payloads. It must be treated according to the strictest stored privacy classification.

For a consistent file-backed backup:

1. stop Simorgh Core or use a SQLite-aware online backup;
2. copy the database with its current WAL state consistently;
3. protect the backup with access controls matching production secrets and private data;
4. restore only into an offline path;
5. start Core and require schema, integrity, payload-hash and indexed-column validation.

Do not edit result rows manually. On corruption or schema mismatch, preserve the database for diagnosis and restore from a verified backup or intentionally start with a new empty authority. Never copy questionable rows into a clean store.

## Current limitations

- only `SpecialistPlanPayload` is registered;
- no public result API is exposed;
- production artifact bytes are not stored by this increment;
- evidence comes only from fake/local tests until Phase 1.5;
- result traces remain process-local;
- there is no distributed multi-process lease;
- no live model/provider/connector/MCP/mutation path is enabled;
- Voice, Notification, Memory, Work Graph and new Android operations remain parked.

## Validation

Ordinary CI is fake/local and zero-cost. Required exact-head gates are documented in [`validation/phase-1-4-typed-results.md`](validation/phase-1-4-typed-results.md). Architecture rationale is recorded in [`adr/0017-typed-specialist-result-authority.md`](adr/0017-typed-specialist-result-authority.md).
