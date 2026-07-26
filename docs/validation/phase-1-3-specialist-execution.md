# Phase 1.3 specialist execution validation

Status: exact-head validation candidate

Authoritative implementation: PR #44 / issue #40.

The candidate includes:

- exact specialist/version registry validation;
- durable `InvocationStore(kind=specialist)` execution and restart replay;
- concrete `SpecialistPlanPayload` rather than arbitrary final dictionaries or raw model text;
- stable context-bundle and cancellation-owner identities;
- absolute and monotonic deadline enforcement;
- privacy-safe specialist start, completion, failure and replay traces;
- zero live provider, connector, MCP or Android side-effect calls in ordinary CI.

This document does not claim acceptance by itself. Phase 1.3 is accepted only after the exact commit containing this record passes Core Ruff, strict MyPy, full Core tests, Android build, JVM tests, lint and APK generation, and the PR has no unresolved review threads.
