---
name: ci-workflow-addition-and-iteration
description: Workflow command scaffold for ci-workflow-addition-and-iteration in Simorgh.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /ci-workflow-addition-and-iteration

Use this workflow when working on **ci-workflow-addition-and-iteration** in `Simorgh`.

## Goal

Adds a new CI workflow YAML file and iteratively updates it to refine or expand the workflow.

## Common Files

- `.github/workflows/*.yml`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Create a new .github/workflows/*.yml file for the CI workflow.
- Iteratively update the workflow YAML file to refine steps, triggers, or add cleanup.
- Optionally, coordinate with related patch or code changes.

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.