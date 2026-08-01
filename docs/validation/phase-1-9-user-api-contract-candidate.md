# Phase 1.9 AvalAI staging foundation and fake canary composition

## Scope

This increment establishes the zero-external contract and composition boundary
for issue #65. It adds no live workflow, credential, production provider call,
public endpoint, connector call, Android behavior or Phase 1.10 workflow.

## Official provider boundary

The implementation is restricted to the documented AvalAI endpoints:

```text
GET  https://api.avalai.ir/user/v1/credit
POST https://api.avalai.ir/user/v1/transactions/lookup
```

Transaction lookup accepts exactly one provider request identity for the fixed
one-call canary. The safe projection keeps model/provider/status/token/cost
metadata and discards safety identifier, IP address, API-key suffix, tools,
grants, packages and every raw response body.

## Delivered contracts

- disabled-by-default `LiveProviderStagingPolicy`;
- exact AvalAI API and User API URL literals;
- reviewed and canonically sorted model allowlist;
- exactly one model call;
- bounded input/output tokens, local estimated cost, exact UNIT cost, UNIT
  credit floor, polling, elapsed time, timeout and response bytes;
- no implicit conversion between provider `UNIT`, IRT and local micro-USD;
- canonical policy and pricing SHA-256;
- safe credit, rate-limit, transaction, token and exact-cost projections;
- UUIDv7 provider transaction identity;
- explicit UNIT and IRT currencies;
- typed sanitized HTTP/transport/limit/response failures;
- deterministic `FakeAvalAIUserAPI` for ordinary CI;
- narrow HTTP client with no arbitrary path, method or request body.

## Fake canary composition

`LiveProviderStagingService` composes the existing durable runtime without a
parallel provider path:

```text
manual typed request
-> disabled-by-default policy check
-> exact pricing/model identity
-> credit and model-catalog preflight
-> BudgetedModelGateway
-> durable InvocationStore reservation/terminalization
-> fixed canary output fingerprint
-> bounded exact transaction lookup
-> immutable sanitized staging result
```

The canary input, instructions and expected output are fixed Core constants.
The selected model is the only model in the staging `ModelCatalog`. A completed
staging report is claimed in `LiveProviderStagingResultStore`; exact replay
returns that report before credit, model discovery, model generation or
transaction lookup, so it creates no second external call or usage charge.

## Failure and privacy behavior

- unreviewed URL, model or pricing authority fails closed;
- missing/empty credentials fail before HTTP entry;
- insufficient UNIT credit or unavailable model blocks before model entry;
- 400/401/403/404/429/5xx responses map to typed codes;
- timeout/transport failures expose no provider or credential body;
- oversized, malformed or schema-expanded responses fail closed;
- exact transaction absence is polled only within reviewed bounds;
- missing/invalid request ID, transaction mismatch, output mismatch and exact
  cost overflow become typed incomplete results and never retry the model;
- provider transport uncertainty remains an incomplete durable result;
- model output text is hashed and counted but never stored in the staging
  result;
- User API private fields never enter returned models, exceptions or traces.

## Deterministic validation

Local zero-external validation before transfer:

```text
focused policy/User-API/service tests: 27 passed
complete local Core suite: 507 passed, 1 existing dependency warning
compileall: passed
Python source line-length check: passed
ordinary network calls: zero
```

The composition syntax repair was applied through exact anchors and validated
before the product commit `c8df54c4431fb3b4845155d6b9cd23505b0c1e55`:

```text
Ruff: passed
strict MyPy: passed across 78 source files
Core tests: 514 passed, 2 existing dependency warnings
```

The one-shot validation workflow removed itself from the product commit. No
credential, protected environment, network request, generated database or
runtime state entered the branch.

## Next gate

This owner-authored documentation commit triggers the ordinary exact-head CI.
That head must pass standard Ruff, strict MyPy, the complete Core suite, Android
build, JVM tests, lint and Debug APK before the fake canary composition can be
accepted. SQLite staging-result durability and the protected manual workflow
remain separate later increments; no live request is permitted until those
boundaries are merged and independently validated.
