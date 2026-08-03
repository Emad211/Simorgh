# ADR 0022: Live-provider staging is manual, pinned and exactly reconciled

- Status: Accepted
- Date: 2026-08-03
- Phase: 1.9
- Issue: #65
- Pull request: #70

## Context

Simorgh needs one real provider canary to validate its native model path against
AvalAI. The validation must not turn staging into a production model endpoint,
let GitHub Actions create new budget, or weaken durable Task, Invocation, Trace,
cancellation, privacy or replay authority.

A provider request may enter AvalAI before a timeout, cancellation or transport
failure becomes observable. Repeating the model request in that state could
create a second charge. AvalAI transaction data can also become available after
the model invocation has already completed, so model execution and billing
reconciliation remain separate.

GitHub environment configuration is external operational state. Repository files
can name an environment and reference a secret, but they cannot prove that the
environment exists, that reviewers or branch restrictions are configured, or
that the secret is present and current.

GitHub requires a workflow configured with `workflow_dispatch` to exist on the
repository default branch before it can be manually dispatched. The complete
Phase 1.9 implementation is developed in PR #70 and cannot be merged before its
live acceptance gate. Directly placing the full unaccepted implementation on
`main` would erase that review boundary, while adding push, pull-request or
schedule triggers would create an automatic paid path.

A reusable workflow can be referenced by an exact commit SHA. Its jobs can retain
the protected environment, while the `github` context remains associated with
the caller. This permits a tiny default-branch dispatcher to remain the only
manual entry and a separately reviewed worker commit to remain immutable.

## Decision

### Two-file topology

1. `.github/workflows/live-provider-staging-dispatch.yml` is the only
   `workflow_dispatch` entry. It is introduced to `main` through a separate,
   zero-live-call bootstrap pull request.
2. `.github/workflows/live-provider-staging.yml` is a reusable worker with
   `workflow_call` only. It has no push, pull-request, schedule or direct manual
   trigger.
3. The dispatcher calls the worker using the full form:

   ```text
   Emad211/Simorgh/.github/workflows/live-provider-staging.yml@<exact-worker-sha>
   ```

   A branch, tag or expression is forbidden in this `uses` reference.
4. The same exact worker SHA is passed as `reviewed_commit_sha`. The dispatcher
   hardcodes `gpt-5.4-mini`; neither worker SHA nor model is a dispatch input.
5. The only dispatcher input is `approved_dispatcher_sha`. Before invoking the
   worker, a pre-secret job requires:
   - repository `Emad211/Simorgh`;
   - ref `refs/heads/main`;
   - a lowercase 40-character approval SHA;
   - equality between `approved_dispatcher_sha` and `github.sha`.
6. The worker independently requires:
   - caller repository `Emad211/Simorgh`;
   - caller ref `refs/heads/main`;
   - caller workflow ref
     `Emad211/Simorgh/.github/workflows/live-provider-staging-dispatch.yml@refs/heads/main`;
   - model `gpt-5.4-mini`;
   - checkout HEAD equal to `reviewed_commit_sha`.
7. The dispatcher does not pass repository or organization secrets. The worker's
   `live-canary` job names environment `live-provider-staging`; only that job may
   resolve environment secret `AVALAI_API_KEY` after protection rules are met.
8. Dispatcher and worker use distinct non-cancelling concurrency groups. The
   worker group remains the final single-live-run authority.
9. The bootstrap pull request contains the dispatcher only. Ordinary CI may run,
   but the live dispatcher is not invoked, no deployment is approved, no secret
   is read and no AvalAI/User API request is made.
10. The dispatcher file merged to `main` must be byte-identical to the reviewed
    dispatcher file validated in PR #70. Any later dispatcher edit invalidates
    prior approval.

### Existing execution and billing controls

11. Live staging remains validation-only and disabled for ordinary Core runtime.
12. A live run requires separate explicit user approval bound to both exact
    lowercase 40-character SHAs:
    - dispatcher SHA currently on `main`;
    - reusable worker SHA pinned by the dispatcher;
    plus model and maximum spend. Prior conversational approval or approval of
    another SHA is invalid.
13. The reviewed model allowlist contains only `gpt-5.4-mini`.
14. The request uses fixed Core-authored canary input and output contracts. User,
    conversation, repository and project content are forbidden.
15. Simorgh permits exactly one model call, zero retries, zero tools, zero
    connector calls, zero failover and one parallel branch.
16. The reviewed hard ceilings are 128 input tokens, 16 output tokens,
    20,000 micro-USD estimated cost, 0.01 `UNIT` exact cost, a 0.10 `UNIT`
    remaining-credit floor and 60,000 ms elapsed time.
17. The canary traverses the existing `AgentTaskControlPlane`,
    `BudgetedModelGateway`, durable `InvocationStore`, correlated Trace and
    staging-result authority. GitHub Actions and the CLI do not create substitute
    authority.
18. Invocation identity is durably claimed and worst-case usage is reserved
    before provider entry. Uncertain entry becomes durable `unknown`; it never
    causes an automatic second model request.
19. After provider completion, only the AvalAI User API transaction lookup for
    the captured provider request ID may be polled. Polling is bounded to six
    attempts separated by 5,000 ms and cannot invoke the model.
20. Phase 1.9 acceptance requires exact transaction identity, provider, model,
    successful status, non-streaming behavior, token usage and exact cost under
    the ceiling. `pending` or `unavailable` reconciliation is incomplete and is
    never interpreted as zero cost.
21. Billing reconciliation is audit evidence. It cannot rewrite completed or
    uncertain Invocation truth, release committed budget or manufacture success.
22. Exact replay uses the same staging, request and invocation identities and
    must add zero provider, catalog, credit or transaction calls and zero usage.
23. The uploaded artifact is a strict versioned sanitized authority. It contains
    bounded IDs, counters, usage, reconciliation and Trace evidence, but no
    prompt, output text, credential, header, IP address, API-key suffix, cookie,
    raw provider/User API body or environment dump.
24. Repository evidence and external operational configuration are reported
    separately. Missing environment/reviewer/secret evidence remains
    `UNVERIFIED`; it is never inferred from workflow YAML.
25. Ordinary CI remains fake and zero-external. Full Core and Android gates must
    be green on the exact dispatcher and worker trees before live approval.

## Operational approval record

The approval record must name all of the following:

```text
exact dispatcher SHA on main
exact reusable worker SHA
exact dispatcher ref = refs/heads/main
model ID = gpt-5.4-mini
max model calls = 1
max input tokens = 128
max output tokens = 16
max estimated cost = 20000 micro-USD
max exact cost = 0.01 UNIT
approval time and approving user
```

Changing either SHA or any fixed field invalidates approval and requires a new
review.

## Consequences

### Positive

- the default-branch requirement is satisfied by a minimal audited file;
- the complete unmerged worker is immutable and referenced by commit SHA;
- the dispatch form cannot choose another worker commit or model;
- caller and worker each validate a different identity boundary;
- no secret is forwarded by the dispatcher;
- environment approval remains immediately before the only credentialed job;
- live cost and provider entry remain bounded and reviewable;
- uncertain provider entry cannot trigger duplicate execution;
- billing evidence is exact without becoming execution authority;
- replay can prove zero duplicate calls and usage.

### Costs

- two exact SHAs must be reviewed and approved;
- the dispatcher bootstrap requires a separate PR and merge to `main`;
- changing the worker requires a new dispatcher pin and bootstrap review;
- environment, reviewer, secret and credential state remain external evidence;
- exact reconciliation may require waiting or a later User API-only lookup.

## Rejected alternatives

### Merge all of PR #70 before live acceptance

Rejected because the Phase 1.9 definition of done requires accepted live evidence
before the feature PR is merged.

### Put the complete live workflow directly on `main`

Rejected because it duplicates the unmerged implementation and creates drift
between the default-branch copy and reviewed Phase 1.9 code.

### Let the dispatcher accept worker SHA or model as inputs

Rejected because dispatch-time choice could execute a different unreviewed
worker or model. Both are hardcoded and statically tested.

### Reference the reusable worker by branch or tag

Rejected because a movable ref can resolve to different code after approval.
Only a full 40-character commit SHA is accepted.

### Forward all caller secrets with `secrets: inherit`

Rejected because the worker must obtain only the environment-scoped credential
from its protected job. The dispatcher passes no secrets.

### Run the canary from ordinary CI

Rejected because ordinary pushes and pull requests must remain zero-external and
must not access provider credentials.

### Call AvalAI from a standalone script

Rejected because it would bypass Task, budget, Invocation, Trace, replay and
uncertainty authorities.

### Retry the model after timeout, cancellation or missing transaction data

Rejected because provider entry may already have occurred. Only the same
transaction ID may be queried through the User API.

### Accept pending reconciliation

Rejected because pending or unavailable billing evidence is incomplete, not zero
cost and not a Phase 1.9 merge acceptance.

### Add a temporary automatic trigger

Rejected because push, pull-request and schedule triggers would open an automatic
paid execution path.

## Follow-up

- use `docs/LIVE_PROVIDER_STAGING_RUNBOOK.md` for bootstrap, setup, dispatch and
  incidents;
- use `docs/validation/phase-1-9-protected-environment-readiness.md` for the
  current evidence audit;
- use `docs/validation/phase-1-9-live-acceptance-checklist.md` for exact approval
  and run acceptance;
- merge the separately reviewed dispatcher bootstrap to `main` with zero live
  execution;
- configure and independently verify the protected environment and secret;
- obtain explicit user approval for both exact SHAs, model and spend;
- execute one canary, obtain exact reconciliation and prove zero-call replay;
- complete review audit and merge Phase 1.9 before beginning Phase 1.10.
