---
name: ci-validation-patch-workflow
description: Workflow command scaffold for ci-validation-patch-workflow in Simorgh.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /ci-validation-patch-workflow

Use this workflow when working on **ci-validation-patch-workflow** in `Simorgh`.

## Goal

Stages a patch, adds/updates CI workflow to validate it, and iterates on the workflow file for validation and cleanup.

## Common Files

- `tools/*.patch`
- `.github/workflows/*.yml`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Stage the patch file in tools/
- Create or update a corresponding .github/workflows/*.yml CI workflow file to validate the patch
- Iterate on the workflow file to enable PR validation and cleanup

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.