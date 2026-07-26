# Durable invocation-store validation evidence

Status: acceptance evidence for ADR 0015 and Phase 1 Step 1.2.

This document records the automated validation boundary for the durable invocation identity, reservation, recovery, and exact-replay implementation. It does not replace the typed contracts, the operational documents, or the exact-head CI requirement.

## Implementation identity

The hardened RC3 product commit is descended from:

```text
ca193325b4efcad2bb48a1d942e8f5cd20e3a533
```

The integrity-checked publisher run was:

```text
https://github.com/Emad211/Simorgh/actions/runs/30207793971
```

The publisher reconstructed the staged RC3 archive and verified this SHA-256 before execution:

```text
dde9c1eed40d319b1fde9e913b3510aa0fd4fa0e36b31436d58c8d231fa2f2a4
```

## Gates passed before product publication

The publisher completed the following gates before the protected fast-forward push:

- transactional exact-head preflight and apply;
- 33 targeted RC3 regression tests;
- exclusive SQLite store-lock and cross-process contention tests;
- canonical JSON, Unicode, result-size, and privacy-error tests;
- model replay independent from the current model catalog;
- durable reservation-before-provider/tool-call tests;
- cancellation and uncertain-call settlement tests;
- terminal idempotency and usage-accounting tests;
- distinct store-path and hard-link-alias checks;
- Ruff across the repository;
- strict MyPy across `services/core/src`;
- the complete Core Pytest suite;
- Android debug build;
- Android JVM unit tests;
- Android lint;
- debug APK generation;
- removal of all temporary publisher bundles and diagnostic workflows.

## Independent merge-candidate CI

The exact commit containing this evidence document must also pass the ordinary repository CI workflow independently of the publisher. A prior publisher result is not sufficient evidence for a later commit.

Required independent checks:

```text
core-quality
android-quality
```

The PR must remain unmerged until both jobs succeed on the exact merge-candidate head and no unresolved review thread remains.

## Cost and external-service boundary

Ordinary validation uses fake/local providers and tools only. It must not contact AvalAI, OpenAI, GitHub connector APIs, MCP servers, Gmail, Calendar, Drive, or another paid/external service.

Completed invocation replay is validated to produce:

```text
new provider calls = 0
new tool calls = 0
new budget reservations = 0
new token/cost usage = 0
```

Interrupted reserved work is accounted conservatively and is never automatically retried.

## Security and privacy boundary

The automated suite verifies:

- immutable invocation and target identity;
- hashed canonical payload integrity;
- indexed-column cross-checks;
- unsupported schema and corruption fail-closed behavior;
- one active Core process per invocation-store path;
- symlink and hard-link lock-file rejection;
- `unknown_side_effect` for uncertain mutations;
- no raw provider/tool exception message persistence;
- no prompt, tool argument, secret, or private marker leakage through validation errors or traces.

The invocation SQLite database is integrity-checked but is not application-level encrypted in this increment. Result contracts must therefore remain minimized and typed.

## Explicit non-claims

This evidence does not claim:

- live provider or live connector validation;
- specialist execution availability;
- automatic or explicit retry support;
- complete task-to-child cancellation propagation;
- MCP, Voice, Notification, or Personal Work Graph integration;
- a new Android mutation boundary;
- physical Samsung Galaxy A53 or One UI validation.

Those capabilities remain separate reviewed increments under the Simorgh implementation master plan.
