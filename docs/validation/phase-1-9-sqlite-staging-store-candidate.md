# Phase 1.9 SQLite staging-result authority candidate

## Scope

This increment remains inside issue #65 and Draft PR #70. It adds durable,
sanitary replay authority for staging reports only. It adds no credential,
live provider call, protected environment, manual workflow, public endpoint,
production enablement, connector call, Android behavior or Phase 1.10 workflow.

## Delivered authority

- `LiveProviderStagingResultStore` now supports exact claim/replay, lookup by
  staging-run identity and invocation identity, deterministic load and close;
- the in-memory store permits one immutable result per run and per durable
  invocation;
- `SQLiteLiveProviderStagingResultStore` uses WAL, `synchronous=FULL`, foreign
  keys, busy timeout and exclusive process ownership;
- schema version, canonical payload SHA-256 and indexed-column identity are
  validated on startup and read;
- exact replay survives close/reopen without any provider or User API call;
- changed content, cross-run invocation reuse, unsupported schema, payload hash
  mismatch, index mismatch, process-lock conflict and closed-store access fail
  closed;
- private output text, credential data and raw provider/User-API bodies are not
  admitted to the stored staging result.

## Validation

The reviewed transfer archive and every extracted file were verified by
SHA-256 before application. A one-shot workflow applied the payload, removed
all workflow/chunk transfer files and passed the complete Core gate before
publishing the product commit.

Product commit:

```text
f8b8f1c7380f786a219213dcceaf0352445b9947
```

Validated before publication:

```text
Ruff: passed
strict MyPy: passed
Core tests: 520 passed
SQLite focused staging tests: passed
ordinary network calls: zero
```

The product PR diff contains no temporary workflow, archive chunk, generated
database, WAL/SHM file or process-lock file.

## Exact-head gate

This owner-authored documentation commit triggers the ordinary repository CI.
The resulting exact PR head must independently pass:

- Core installation, Ruff, strict MyPy and all tests;
- Android build, JVM tests, lint and Debug APK upload;
- zero live model/provider/connector/MCP or paid external calls.

Only after this gate may Phase 1.9 continue to Core lifespan ownership and the
protected manual workflow. No live request is permitted by this increment.
