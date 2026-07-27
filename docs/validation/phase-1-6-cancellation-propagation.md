# Phase 1.6 durable cancellation propagation validation

- Tracking issue: #53
- Pull request: #54
- Branch: `core/cancellation-propagation`
- Base Phase 1.5 merge: `7fef6a5262de1e84be89c9afc30c25053945a4ac`
- Product acceptance candidate: `c45ad0d4d4640aee60ddbdecda627030bedb702e`
- Documentation-synchronized predecessor: `a0eb60f6619f129ca807eeb3821b520b1bfc7980`
- Status: implementation, acceptance and operational documentation complete; final exact-head Core/Android CI and review audit validating

## Scope under validation

This record covers only Phase 1 Step 1.6:

```text
durable task cancellation request
  → durable invocation ownership fence
  → block later invocation begin/reserve
  → process-local owner signal
  → pending cancellation
  → optional typed adapter cancellation
  → conservative reserved settlement
  → immutable cancellation result and audit metadata
```

It does not validate Voice, Notification, MCP, Memory, Work Graph, retry/compensation, live provider cancellation, GitHub mutation or new Android behavior.

## Product acceptance evidence

The Phase 1.6 acceptance finalizer validated the complete generated product candidate before publishing `c45ad0d4d4640aee60ddbdecda627030bedb702e`.

```text
Acceptance source head: b3c4ffe7e947112fc758c905db5d8eb854fb0261
Acceptance workflow: 30279133534
Conclusion: success
Published product candidate: c45ad0d4d4640aee60ddbdecda627030bedb702e
Core tests: 360 passed
Ruff: passed
strict MyPy: passed
```

The publisher removed its temporary scripts and workflow before committing the product candidate. They are not part of the PR product diff.

The ordinary CI attached to the acceptance source head also completed successfully. The exact final PR head receives a separate ordinary CI gate because the bot-published product/documentation commits required workflow approval rather than reporting product failures.

## Documentation synchronization evidence

The documentation predecessor `a0eb60f6619f129ca807eeb3821b520b1bfc7980` adds and synchronizes:

- `docs/CANCELLATION_PROPAGATION.md`;
- ADR 0019;
- this acceptance record;
- Phase 1.5 completion and Phase 1.6 validating status in the master plan;
- cancellation semantics in the agent runtime guide;
- documentation index, roadmap, ADR and durability references;
- completed Phase 1.5 status in its operational guide and ADR;
- a supersession link from the Phase 1.6 start record.

The exact-anchor documentation publisher removed itself and its script before committing. A changed-file audit confirms no temporary publisher file remains in the pull request.

## Contract validation

Validated cancellation contracts include:

- immutable versioned task cancellation request;
- stable or caller-supplied cancellation identity;
- bounded normalized operator reason;
- requester authority and observed task phase/version;
- deterministic ownership references and snapshot hash;
- typed adapter acknowledgement;
- bounded per-invocation settlement outcome;
- immutable task cancellation result;
- stable audit event identity;
- strict extra-field rejection and hidden inputs in validation errors.

## Ownership and admission validation

Acceptance tests prove:

- task-to-invocation enumeration across specialist, model and tool kinds;
- deterministic `(created_at_ms, invocation_id)` ordering;
- terminal filtering;
- immutable ownership after claim;
- cancellation owner identity stored with invocation authority;
- parent/child ownership survives SQLite reopen;
- child invocation requires an existing terminal same-task parent and exact next attempt;
- cross-task parent ownership fails closed;
- a durable fence blocks later invocation `begin`;
- a durable fence blocks later invocation `reserve`;
- an invocation admitted before the fence appears in the snapshot and is settled.

## Idempotency and race validation

Validated behavior includes:

- exact repeated cancellation returns retained state;
- changed cancellation content conflicts;
- cancellation ID reuse across tasks conflicts;
- simultaneous identical cancellation converges on one authoritative request;
- one process-local owner signal at most once;
- one adapter cancellation attempt per cancellation/invocation pair;
- late owner registration is signalled and blocked;
- late adapter registration is blocked;
- owner/adapter unregistration is identity checked;
- process restart does not recreate stale local handles.

## State settlement validation

| Prior state | Validated final behavior |
|---|---|
| pending | `cancelled`, zero usage |
| reserved read with typed non-entry proof | `cancelled`, reservation released |
| reserved read without non-entry proof | `unknown`, reservation conservatively committed |
| reserved mutation | `unknown_side_effect`, reservation conservatively committed |
| completed | unchanged result and usage |
| failed/cancelled/expired/unknown/unknown-side-effect | unchanged terminal state |

Additional tests prove that adapter `accepted` without proof does not overclaim non-execution and that disabling adapter hooks preserves conservative settlement.

## Durability and accounting validation

Validated behavior includes:

- cancellation request/result persistence in task authority;
- invocation fence persistence in SQLite invocation authority;
- restart-safe admission blocking;
- pending/reserved settlement after reopen;
- completed invocation immutability;
- conservative reserved usage commitment;
- proof-of-non-entry release only for non-mutation work;
- duplicate cancellation does not alter usage;
- task aggregate usage remains monotonic;
- no cancellation path creates a model/tool/specialist call;
- Phase 1.5 exact completed GitHub replay remains unchanged.

## Privacy validation

Unique private markers are asserted absent from:

- cancellation audit traces;
- failure metadata;
- bounded cancellation results;
- status projections.

The tests also prove:

- operator reason text is not copied into trace metadata;
- task input is absent from cancellation audit events;
- adapter exception messages are converted to typed uncertainty and not persisted;
- raw provider/tool/connector payloads are absent;
- credentials and environment variables are never accepted into cancellation contracts.

## Operational validation

Documented operations cover:

- ownership and source of truth;
- cancellation ordering;
- state-transition matrix;
- adapter acknowledgement semantics;
- budget and accounting behavior;
- restart recovery;
- race and idempotency rules;
- audit/redaction boundary;
- adapter disable switch;
- store incident response;
- current limitations.

References:

- [`../CANCELLATION_PROPAGATION.md`](../CANCELLATION_PROPAGATION.md)
- [`../adr/0019-durable-cancellation-propagation.md`](../adr/0019-durable-cancellation-propagation.md)

## Remaining final merge gates

Before PR #54 may merge:

- run ordinary CI on the exact final candidate;
- confirm Core install, Ruff, strict MyPy and all tests pass;
- confirm Android build, JVM tests, lint and debug APK generation pass;
- audit unresolved review threads and submitted reviews;
- update the PR body with the exact candidate and CI evidence;
- mark the PR ready and merge only with expected-head protection.
