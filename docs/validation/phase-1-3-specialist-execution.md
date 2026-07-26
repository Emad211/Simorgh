# Phase 1.3 specialist execution validation

Status: Accepted under ADR 0016; merge remains gated on exact-head CI.

Authoritative implementation: PR #44 / issue #40.

Accepted scope:

- exact specialist/version registry validation;
- durable `InvocationStore(kind=specialist)` execution and restart replay;
- concrete `SpecialistPlanPayload` rather than arbitrary final dictionaries or raw model text;
- stable context-bundle and cancellation-owner identities;
- absolute and monotonic deadline enforcement;
- privacy-safe specialist start, completion, failure and replay traces;
- zero live provider, connector, MCP or Android side-effect calls in ordinary CI.

Product validation evidence:

- product authority commit: `4e34e19ca00f0f512adacd3d6b09ee3344399295`;
- independently triggered exact-head candidate: `9b9231465c3a0f3440b63ccd4be2b4527804b252`;
- CI run `30213193745`: Core install, Ruff, strict MyPy and full tests passed;
- CI run `30213193745`: Android assemble, JVM tests, lint and debug APK generation passed;
- PR #44 had no unresolved review threads at the candidate head.

Final evidence rule: the commit containing this record must itself have successful `core-quality` and `android-quality` jobs. Its run ID is intentionally not embedded here, because recording that ID would create a new commit and invalidate the exact-head claim.
