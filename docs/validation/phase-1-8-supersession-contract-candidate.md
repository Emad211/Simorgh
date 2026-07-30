# Phase 1.8 typed trace supersession contract candidate

## Boundary

This checkpoint introduces the durable contract and store semantics required to supersede historical terminal trace status without deleting or rewriting prior events. It does not yet change retained-source reconciliation behavior; that is the next Phase 1.8 increment.

## Clean product commit

- Commit: `7291c701e11cbb0d0d7d7a83a228eb1f40e276e7`
- Direct parent: `09d368cc49a8bf9e52ef5dd36c6f903524dcd849`
- Candidate CI run: `30501680626`
- Product diff: exactly four files
- Temporary patcher and workflow changes are absent from the clean commit

## Implemented semantics

- `trace_superseded` reopens the current status of a terminal trace while preserving historical terminal and gap events;
- `trace_resolved` establishes the current terminal disposition for one superseded trace epoch;
- only a typed supersession may admit fresh events after current terminal status;
- supersession causation must reference an existing terminal status event;
- resolution causation must reference an existing nonterminal supersession event;
- only existing typed gap event IDs may be marked resolved for current status;
- historical `gap_count` and `gaps` remain immutable audit history;
- `unresolved_gap_count` and `unresolved_gap_event_ids` independently control whether current disposition remains `incomplete_gap`;
- an unrelated unresolved gap still dominates current status as `incomplete_gap`;
- SQLite close/reopen reconstructs the same superseded current status;
- legacy terminal-fence error compatibility remains unchanged.

## Covered acceptance

- terminal plus historical source-mismatch gap becomes nonterminal after typed supersession;
- the historical gap remains visible while unresolved count becomes zero;
- fresh causal source events can append only after supersession;
- typed resolution restores a terminal current disposition;
- unrelated unresolved gaps remain visible and force `incomplete_gap`;
- invalid terminal/nonterminal supersession detail shapes are rejected;
- SQLite restart reconstruction is exact.

## Required exact-head validation

The standard repository CI must pass on the commit containing this record:

```text
ruff check .
mypy services/core/src
pytest
Android assembleDebug
Android JVM tests
Android lint
Debug APK upload
```

Phase 1.8 remains Draft. The next increment integrates supersession and resolution into retained-source reconciliation, including retry, cancellation and source-evolution replay.
