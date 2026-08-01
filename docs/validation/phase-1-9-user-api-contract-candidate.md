# Phase 1.9 AvalAI User API and staging-policy foundation

## Scope

This increment establishes the zero-external contract boundary for issue #65.
It adds no live workflow, credential, provider request, production model traffic,
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
- bounded input/output tokens, estimated cost, credit floor, polling, timeout
  and response bytes;
- canonical policy SHA-256;
- safe credit, rate-limit, transaction, token and exact-cost projections;
- UUIDv7 provider transaction identity;
- explicit UNIT and IRT currencies;
- typed sanitized HTTP/transport/limit/response failures;
- deterministic `FakeAvalAIUserAPI` for ordinary CI;
- narrow HTTP client with no arbitrary path, method or request body.

## Failure and privacy behavior

- unreviewed URL or model authority fails closed;
- missing/empty credentials fail before HTTP entry;
- 400/401/403/404/429/5xx responses map to typed codes;
- timeout/transport failures expose no provider or credential body;
- oversized, malformed or schema-expanded responses fail closed;
- exact transaction absence remains a typed not-found/pending result;
- User API private fields never enter returned models, exceptions or traces;
- no automatic polling or model-call retry is introduced in this increment.

## Local validation

```text
focused policy/User-API tests: 15 passed
compileall: passed
Python source line-length check: passed
ordinary network calls: zero
```

The exact PR head must still pass standard Ruff, strict MyPy, the complete Core
test suite, Android build, JVM tests, lint and Debug APK before this foundation
can be accepted. A later Phase 1.9 increment may compose these contracts with
the existing `BudgetedModelGateway`; no live request is permitted until the
manual protected workflow and complete fake acceptance boundary are merged.
