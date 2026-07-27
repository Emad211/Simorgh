# ADR 0018: Governed read-tool authority and typed GitHub evidence

- Status: Accepted; merged through PR #52
- Date: 2026-07-27

## Context

Simorgh already had durable tasks, durable model/tool/specialist invocation identity, a budgeted tool gateway and immutable typed result/evidence metadata. It did not yet have a reviewed connector contract proving that one selected specialist could read current external evidence without inheriting arbitrary connector capabilities, raw payloads, credentials or mutation authority.

GitHub is the first connector because repository research is the Phase 1 vertical slice. GitHub content is still untrusted external input, including content from an allowed repository.

## Decision

Simorgh owns a connector-neutral `GovernedReadAdapter` protocol and a GitHub-specific exact-version request/projection contract. A Core compiler derives each request from the durable routed task and active specialist/manifest policy. Effective authority is the intersection of task data sources, exact specialist tool/connector allowlists, reviewed connector manifest, privacy/freshness/cache limits, cancellation/deadline state and effective budget.

The initial GitHub manifest exposes only search, fetch-file, fetch-issue and fetch-pr. It forbids mutation, arbitrary endpoint access, credentials in requests, raw binary content, archive extraction, LFS download, submodule traversal and symlink following.

Calls use the existing `BudgetedToolGateway`. The gateway durably claims identity, reserves request and invocation usage, invokes once, validates the typed projection and commits or terminalizes. Deterministic post-call policy/contract rejection is `failed` with sanitized metadata and committed usage; transport uncertainty is `unknown`. Completed calls replay exactly after restart with no adapter entry or new charge.

Validated projections map deterministically to ADR 0017 `EvidenceReference` metadata with freshness, cache, taint, citation, privacy and canonical SHA-256. Raw provider responses and body text never become trace metadata or final result authority.

Ordinary CI uses a deterministic zero-network fake adapter. Live validation is a separate explicit future staging boundary.

## Consequences

- Connector capability cannot grant permission.
- A model cannot select tools, credentials, privacy ceiling or mutation authority.
- Current tasks fail closed on stale or cache-only evidence.
- Private projections are rejected unless both request ceiling and reviewed manifest permit them.
- Tool cost remains conservative when a call returned but its projection was rejected.
- External text remains tainted for Phase 1.7 Context Compiler.
- Final Persian reporting and automatic multi-tool composition remain Phase 1.10.

## Rejected alternatives

- Calling the GitHub REST/GraphQL API directly from a specialist.
- Passing an unrestricted connector catalog or arbitrary URL into model context.
- Treating GitHub content as trusted because a repository is allowed.
- Persisting raw provider payloads and filtering them later.
- Retrying uncertain calls under the same invocation ID.
- Building a second budget or invocation runtime beside `BudgetedToolGateway`.
- Enabling mutation, Voice, MCP or live credentials in this trust-boundary PR.

## Follow-up

Phase 1.6 adds complete cancellation propagation, Phase 1.7 compiles tainted evidence into bounded context, Phase 1.8 completes end-to-end trace, Phase 1.9 adds explicit live staging, and Phase 1.10 composes the complete Persian GitHub workflow.
