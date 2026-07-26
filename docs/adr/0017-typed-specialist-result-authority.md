# ADR 0017: Typed specialist result authority

- Status: Proposed
- Date: 2026-07-26
- Governing issue: #46
- Implementation PR: #48
- Supersedes: none
- Depends on: ADR 0016 and the merged Phase 1.3 specialist execution authority

## Context

Phase 1.3 can execute one selected specialist and durably replay its typed execution result. That invocation payload is necessary for execution recovery, but it is not yet the long-lived authority for result families, evidence, artifacts, privacy, retention or user-facing rendering.

Persisting arbitrary model text, free dictionaries, raw connector responses or presentation text as a final result would collapse several trust boundaries:

- schema identity and validation;
- producer and invocation identity;
- cost-accounting provenance;
- artifact integrity;
- evidence freshness and taint;
- privacy classification and retention;
- deterministic replay;
- localized presentation.

Phase 1.4 therefore needs a separate immutable result authority whose creation is conditional on a completed durable specialist invocation.

## Decision

### 1. Exact typed result registry

Result families are admitted through an immutable exact-version registry. The first registered family is:

```text
output contract: simorgh.typed-plan.v1
result schema:   simorgh.specialist-plan-result
schema version:  1.0
payload:         SpecialistPlanPayload
```

Unknown schema IDs, unknown versions, duplicate registrations, output-contract mismatches and arbitrary payload fields fail closed.

### 2. Immutable authoritative result

`AuthoritativeSpecialistResult` binds:

- stable deterministic result ID;
- request and invocation IDs;
- exact producer agent ID and version;
- output contract, result family, schema ID and schema version;
- typed payload;
- direct invocation usage-reference identity;
- artifact and evidence references;
- explicit uncertainty and verification requirements;
- privacy and retention classification;
- creation and completion chronology;
- canonical SHA-256;
- fresh or replayed disposition.

The canonical hash excludes presentation and replay disposition. A replay can mark the returned view as replayed, but cannot rewrite the stored authority.

### 3. Artifact references, not uncontrolled bytes

The authority stores artifact metadata only:

- artifact ID;
- canonical content hash;
- media type and byte size;
- request, invocation and producer identity;
- privacy and retention;
- storage disposition and bounded storage reference;
- chronology and optional expiry;
- optional encryption-key reference.

Tests may construct deterministic fake bytes and validate them against the declared size and SHA-256. Production artifact bytes require a later dedicated storage boundary. Public storage is valid only for public artifacts.

### 4. Evidence references remain tainted and presentation-neutral

Evidence metadata includes source/tool/connector identity, observation time, freshness, cache disposition, projection hash, bounded citation reference, optional artifact link, privacy and untrusted-source taint. Raw connector bodies and private content are not admitted into trace metadata or evidence references.

### 5. Privacy and retention compose conservatively

A result may never downgrade linked artifact or evidence privacy. Its effective privacy is the strictest linked classification. Its effective retention is at least the longest linked artifact retention. Legal-hold artifacts cannot expire.

### 6. Dedicated durable store

The result authority has strict in-memory and SQLite WAL implementations. SQLite uses:

- a distinct database path and process-ownership lock;
- schema-version checks;
- `synchronous=FULL`;
- canonical payload JSON and SHA-256;
- indexed-column versus payload validation;
- immutable one-result-per-invocation identity;
- corruption latching and fail-closed reads.

A completed replay returns the stored result without a new specialist call, new usage charge, privacy downgrade, retention rewrite or artifact/evidence replacement.

### 7. Cross-authority terminalization

`SpecialistResultTerminalizer` verifies that:

- the invocation exists;
- it is a completed specialist invocation;
- the durable execution payload equals the supplied typed result;
- committed usage equals invocation accounting;
- the result schema is registered;
- the immutable result can be claimed durably.

Phase 1.4 success is withheld if result persistence fails. The Phase 1.3 invocation remains the execution-recovery authority; the Phase 1.4 store is the final typed-result authority.

### 8. Presentation is outside authority fields

The first renderer deterministically produces Persian presentation from the typed plan. Its output explicitly declares itself non-authoritative and references the authoritative result ID and canonical hash. Rendering does not mutate or rehash the result.

### 9. Privacy-safe trace

Result traces contain only bounded metadata such as result/schema IDs, canonical hash, counts, privacy, retention and replay disposition. Payload, evidence bodies, artifact bytes and presentation text are excluded.

## Failure semantics

- Unknown or mismatched schema: reject before durable result claim.
- Invocation mismatch: reject; do not create a result.
- Result-store failure: do not report Phase 1.4 success.
- Changed payload under one invocation/result ID: conflict.
- Changed artifact/evidence metadata on replay: conflict.
- Corrupt payload hash or indexed columns: latch the store unhealthy and fail closed.
- Interrupted Core process after Phase 1.3 completion but before Phase 1.4 claim: the durable invocation can be terminalized again idempotently.
- Missing artifact bytes: references remain metadata only; no false claim that bytes were stored.

## Consequences

Positive:

- final specialist results are schema-versioned and replayable;
- artifact/evidence provenance is explicit;
- privacy and retention cannot silently weaken;
- Persian presentation can evolve without changing authority identity;
- Phase 1.5 governed read tools have a typed evidence target.

Costs and limits:

- only the typed-plan family is registered in this increment;
- production artifact-byte storage is intentionally deferred;
- there is no public result endpoint yet;
- there are no live connectors, model calls, mutations, MCP, Voice, Notification, Memory or new Android effects.

## Validation required before acceptance

- Ruff, strict MyPy and full Core tests pass on the exact PR Head;
- Android build, JVM tests, lint and debug APK pass on the exact PR Head;
- restart replay returns the identical result and does not duplicate usage;
- corruption, schema mismatch, identity mismatch and changed references fail closed;
- private payload markers do not appear in errors or traces;
- all review threads are resolved;
- Phase 1.4 documentation and validation evidence are synchronized.
