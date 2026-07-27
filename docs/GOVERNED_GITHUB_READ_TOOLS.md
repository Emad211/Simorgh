# Governed GitHub read tools

Status: Phase 1.5 merged through PR #52. The production boundary remains read-only and fake/local in ordinary CI; live validation is a later staging step.

## Purpose

Phase 1.5 lets the already-routed `github.read` specialist obtain bounded current evidence without granting arbitrary GitHub, shell, browser, git, credential or mutation authority.

```text
durable routed task
  → Core request compiler
  → task/source ∩ specialist/tool ∩ reviewed manifest
  → durable tool invocation claim
  → request-budget reservation
  → durable invocation reservation
  → one structured adapter call
  → typed bounded projection
  → tainted EvidenceReference metadata
  → exact durable replay
```

## Connector-neutral boundary

`GovernedReadAdapter[RequestT, ProjectionT]` exposes only a stable connector ID/version and one typed asynchronous `invoke` operation. The GitHub specialization accepts `GovernedGitHubReadRequest` and returns `GitHubReadProjectionEnvelope`.

Adapter discovery is not permission. The effective authority is always the intersection of the durable task, exact specialist version, specialist tool/connector allowlists, reviewed manifest, privacy ceiling, freshness/cache requirement, deadline/cancellation state and effective budget.

## Exact operations

Only these identities exist in the initial manifest:

```text
github.search
github.fetch-file
github.fetch-issue
github.fetch-pr
```

There is no arbitrary REST or GraphQL endpoint, URL fetch, shell, git clone, archive extraction, Git LFS download, submodule traversal, symlink following or mutation operation.

## Core-authored request

The compiler binds:

- parent request and optional parent specialist invocation IDs;
- stable tool invocation and cancellation-owner IDs;
- exact `github.read` version;
- exact effective data source `github`;
- discriminated operation arguments;
- response/text/item/page limits;
- cache policy and minimum freshness;
- privacy ceiling;
- absolute deadline and effective monotonic budget timeout.

Requests reject extra fields, path escapes, empty queries, unsafe refs, oversized canonical JSON and any data-source widening. Credentials and secret references are absent from the request contract.

## Reviewed manifest

The immutable manifest records the connector and contract versions, exact read-only tool schemas, request/response/text/item/page/timeout ceilings, allowed GitHub hosts, explicit-ref requirement, cache/freshness/cancellation support, private-repository policy and trace/content restrictions.

The default manifest does not allow private projections. A future live adapter may use an adapter-owned secret reference internally, but the credential never enters a request, projection, invocation record, trace or specialist result.

## Typed projections

Search projections include bounded repository identity, default branch, visibility, description/topics and match metadata. File projections include explicit repository/ref/path, optional resolved ref SHA, blob SHA, byte count, object kind and one of complete, truncated, metadata-only or binary-rejected dispositions. Issue and PR projections carry bounded state/body metadata with explicit truncation reasons; PRs also carry check and review summaries.

Every envelope binds canonical SHA-256 and exact canonical JSON byte count, observation/freshness times, cache disposition, citation reference, privacy class and mandatory untrusted/tainted flags. Raw provider payloads are never returned or persisted.

Non-regular file objects remain metadata-only. Binary content is never admitted. Truncation is never silent: a truncated or metadata-only projection must contain a bounded reason.

## Budget, durability and replay

The existing `BudgetedToolGateway` remains the only tool-call authority:

```text
validate policy
  → InvocationStore.begin
  → BudgetAccount.reserve(tool_calls=1)
  → InvocationStore.reserve
  → adapter call once
  → validate typed projection and policy
  → BudgetAccount.reconcile
  → InvocationStore.complete or sanitized failure/unknown
```

A deterministic post-call projection rejection is terminal `failed` with one committed tool call and no private payload. A transport exception after durable reservation is `unknown`, because the connector may have received the call. It is never automatically retried.

Completed SQLite replay returns the identical typed envelope and evidence hash without entering the adapter, creating a new reservation or charging a fresh request budget.

## Freshness and cache

`current` and `execution_bound` tasks compile to `live_only` with a minimum freshness time. Immutable or `cached_ok` tasks may accept a valid cache hit. A live-only request rejects cache hits, stale/unknown freshness and projections whose freshness horizon is older than the minimum.

## Privacy and trace boundary

Traces contain invocation IDs, agent/version, connector/tool identity, effect, usage, cache outcome and sanitized terminal reason. They do not contain arguments, repository body text, file text, provider responses, credentials, headers, private markers or adapter exception messages.

Typed GitHub text remains external untrusted input. Evidence is always marked tainted for the later context compiler. This step does not place GitHub body text into final specialist-result or presentation authority.

## Cancellation and incident response

Phase 1.5 accepts an owned in-process cancellation token before invocation claim and relies on the durable task budget cancellation flag to block new reservations. Complete task-to-child cancellation enumeration remains Phase 1.6.

To disable the connector, remove the tool from the reviewed manifest or remove `github` from the task/specialist intersection. Do not bypass a failed manifest, integrity, privacy, freshness or storage check. Transport uncertainty must remain terminal until an operator investigates the invocation record.

## Validation

Ordinary CI uses `FakeGitHubReadAdapter` only and performs zero GitHub network or credential calls. It validates all four projection families, policy intersection, request/response bounds, private and freshness rejection, cancellation, deterministic failure sanitization, exact SQLite replay, Ruff, strict MyPy, full Core tests and unchanged Android build/JVM/lint/APK gates.

An optional future live-validation workflow must be manually triggered, explicitly budgeted, credential-isolated and use the same contracts. It is not required for Phase 1.5 merge.

## Current limitations

- no live GitHub adapter is enabled in ordinary runtime or CI;
- no automatic multi-tool loop or final Persian repository report;
- no public tool-execution endpoint;
- no complete task-to-child cancellation propagation;
- no Context Compiler, complete trace, Voice, Notification, Memory, MCP or Android side effect;
- no GitHub mutation of any kind.
