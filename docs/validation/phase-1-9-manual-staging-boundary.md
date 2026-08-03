# Phase 1.9 protected manual staging boundary

## Scope

This increment creates the reviewed execution boundary required before the first
real AvalAI canary. It does **not** dispatch the workflow, read a real credential
or make a provider/User API request during implementation or ordinary CI.

The boundary consists of:

- a dedicated composition CLI;
- a versioned sanitized artifact authority;
- a manual-only protected GitHub Actions workflow;
- fake zero-network composition acceptance;
- static workflow and privacy tests;
- exact direct dependency constraints for the live workflow.

## Native composition

The CLI enters the existing Core lifespan and therefore reuses the native:

```text
InvocationStore
TraceStore
LiveProviderStagingResultStore
BudgetedModelGateway
LiveProviderStagingService
```

It does not create a parallel invocation, budget, Trace or result authority.
The fixed Core-authored canary remains inside the existing staging contracts.
The selected model is restricted to the reviewed repository allowlist and the
policy retains `max_model_calls=1`, `max_retries=0`, no tools, no streaming and
no provider/model failover.

The CLI wraps the provider and User API only with bounded call counters. After
the first result is durably claimed, it runs the exact same staging identity a
second time and records the external-call and committed-usage deltas. A passing
artifact requires:

- exactly one first-run model request;
- exactly one model-catalog and credit preflight;
- at least one bounded transaction lookup;
- exact completed reconciliation;
- retained Invocation and terminal Trace evidence;
- replay of the identical result identity;
- zero provider, model-catalog, credit or transaction call on replay;
- zero committed-usage change on replay.

## Sanitized artifact

`LiveProviderStagingArtifact` is strict, immutable and versioned. It contains
only typed IDs, bounded counters, the already-sanitized staging result, validated
Trace evidence, replay proof, usage vectors and workflow/source-commit metadata.

Its canonical SHA-256 and UUID identity exclude only their own identity fields.
The writer uses canonical JSON, a one-megabyte ceiling, atomic replacement and
mode `0600`. The verifier reparses the strict contract and checks the canonical
hash and identity.

The artifact privacy scan rejects:

- the fixed prompt, instruction and expected output strings;
- authorization/bearer markers;
- API-key, cookie and header markers;
- IP, safety-identifier and raw-response markers;
- environment-dump markers;
- the exact runtime credential value supplied only in process memory.

A failed run may emit a typed failed artifact, but the workflow exits nonzero on
preflight, execution, incomplete reconciliation, Trace or replay failure.

## Workflow boundary

`.github/workflows/live-provider-staging.yml` has only `workflow_dispatch`.
It has no push, pull-request or schedule trigger. It requires:

- an exact reviewed 40-character commit SHA;
- the single reviewed model choice;
- one repository-wide concurrency group with no cancellation of an active run;
- read-only repository permissions;
- exact-SHA action references;
- a pre-secret Ruff, strict MyPy and fake-test job;
- a `live-provider-staging` protected environment for the live job;
- `AVALAI_API_KEY` referenced only in the one live execution step;
- isolated temporary SQLite authorities;
- schema/hash/privacy verification before artifact acceptance;
- upload of only the sanitized JSON artifact.

The repository operator must configure the protected environment, optional
required reviewers and environment secret before any dispatch. Merely committing
the workflow does not authorize or execute a live call.

## Ordinary CI guarantee

Ordinary CI never references `AVALAI_API_KEY`, the live CLI or the live workflow.
All new acceptance uses fake provider/User API adapters and in-memory SQLite
composition. Static tests reject trigger widening, unpinned actions, secret
placement outside the protected live step, missing pre-secret gates and removal
of artifact verification.

## Non-goals

- no workflow dispatch in this increment;
- no real API key use;
- no real provider/User API request;
- no production or autonomous model enablement;
- no public endpoint;
- no retry/failover change;
- no Phase 1.10 work.
