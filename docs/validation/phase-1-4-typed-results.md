# Phase 1.4 typed specialist results — validation record

- Status: Validation in progress
- Governing issue: #46
- Pull request: #48
- Branch: `core/typed-specialist-results`
- Authority boundary: typed specialist result, evidence and artifact metadata persistence

## Scope under validation

This increment validates the transition from the completed Phase 1.3 specialist invocation into one immutable Phase 1.4 result authority.

Included:

- exact result-schema/version registry;
- `simorgh.typed-plan.v1` / `SpecialistPlanPayload` family;
- immutable result identity and canonical SHA-256;
- artifact metadata and deterministic fake-byte integrity checks;
- evidence source, freshness, cache, citation and taint metadata;
- uncertainty and verification requirements;
- conservative privacy and retention composition;
- in-memory and SQLite WAL result stores;
- restart replay without a new specialist call or usage charge;
- cross-check against durable invocation payload and committed usage;
- deterministic Persian presentation outside authority fields;
- metadata-only result traces;
- Core lifespan and distinct-store-path integration.

Excluded:

- live provider/model calls;
- live GitHub or other connectors;
- mutation executors;
- public result API;
- production artifact-byte storage;
- MCP, Voice, Notification, Memory and new Android behavior.

## Required automated evidence

### Core contract and persistence tests

- raw text and arbitrary dictionary payloads rejected;
- duplicate/unknown schema registrations rejected;
- stable canonical result hash;
- renderer cannot mutate the authority;
- artifact size/hash/media/storage rules fail closed;
- evidence taint, freshness and artifact linkage validated;
- strictest privacy and retention propagated;
- in-memory replay returns one immutable result;
- SQLite restart replay returns identical result ID/hash;
- changed payload or changed reference metadata conflicts;
- durable invocation mismatch prevents result creation;
- corrupt payload hash and unsupported schema fail closed;
- process ownership lock prevents concurrent SQLite authority;
- private payload markers absent from failures and traces;
- application startup loads the result store and shutdown resets it;
- result store path cannot alias task, invocation or Android action stores.

### Repository gates

```text
ruff check .
mypy services/core/src
pytest --junitxml=artifacts/junit.xml
gradle :apps:android:assembleDebug \
       :apps:android:testDebugUnitTest \
       :apps:android:lintDebug
```

## Exact-head record

The final commit SHA, CI run IDs, test count and conclusions are recorded only after all exact-head jobs complete. This document must not claim acceptance while any gate is queued, skipped, action-required or failed.

## Acceptance checklist

- [ ] Ruff passed on exact PR Head
- [ ] strict MyPy passed on exact PR Head
- [ ] full Core pytest passed on exact PR Head
- [ ] Android build passed on exact PR Head
- [ ] Android JVM tests passed on exact PR Head
- [ ] Android lint passed on exact PR Head
- [ ] debug APK artifact produced
- [ ] no unresolved review thread
- [ ] ADR 0017 accepted
- [ ] master plan and documentation synchronized
- [ ] PR remains limited to Phase 1.4
