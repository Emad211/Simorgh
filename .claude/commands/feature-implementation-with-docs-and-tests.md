---
name: feature-implementation-with-docs-and-tests
description: Workflow command scaffold for feature-implementation-with-docs-and-tests in Simorgh.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /feature-implementation-with-docs-and-tests

Use this workflow when working on **feature-implementation-with-docs-and-tests** in `Simorgh`.

## Goal

Implements a core feature, updates documentation, and adds/updates tests for the new functionality.

## Common Files

- `services/core/src/**/*.py`
- `docs/validation/*.md`
- `services/core/tests/*.py`
- `.github/workflows/*.yml`
- `tools/*.patch`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Implement or update core logic in services/core/src/
- Add or update documentation in docs/validation/
- Add or update tests in services/core/tests/
- Optionally update CI workflow and patch files

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.