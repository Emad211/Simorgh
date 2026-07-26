# Phase 1.5 governed GitHub read tools — validation record

## Scope

- Parent roadmap step: Phase 1 Step 1.5.
- Tracking issue: #51.
- Implementation pull request: #52.
- Trust boundary: Core-governed, read-only GitHub evidence acquisition.
- Supported operations: bounded search, file projection, issue projection, and pull-request projection.
- Explicitly excluded: mutation, comments, reactions, merges, workflow dispatch, arbitrary REST/GraphQL, shell, clone, browser automation, Voice, MCP, Notification, Memory, Work Graph, and new Android side effects.

## Candidate validated before this record

The security-hardening candidate at commit `f366e0ab674985851388c1361bdbe7d5a7d56903` was produced only after the self-finalizing acceptance gate completed successfully.

Validated Core gates:

- Ruff: passed.
- strict MyPy: passed across 49 source files.
- pytest: 340 passed.
- ordinary test execution used the deterministic fake GitHub adapter and made zero live GitHub or paid external calls.

## Acceptance and security evidence

The candidate proves:

- exact read-only tool and connector authority;
- task, specialist, manifest, budget, deadline, freshness, cache, cancellation, and privacy-policy intersection;
- typed, bounded projections for search, files, issues, and pull requests;
- canonical fingerprints and deterministic replay without an additional connector call or duplicate usage;
- fail-closed rejection for malformed or policy-invalid projections;
- `unknown` settlement for unexpected adapter uncertainty;
- non-public repository visibility cannot be under-classified as public;
- private markers and unexpected adapter details do not enter durable invocation records or traces;
- one committed tool call is retained when a post-call projection is rejected;
- no temporary publisher workflow or patch payload remains in the pull-request diff.

## Exact-head standard CI

This documentation-only commit exists to trigger the repository's normal CI on the complete merge candidate. The required final gate is:

- Core lint, strict type checking, and all tests;
- Android `assembleDebug`, JVM unit tests, and `lintDebug`;
- successful debug APK artifact upload.

The pull request must not be marked ready or merged until those checks succeed on its exact head.
