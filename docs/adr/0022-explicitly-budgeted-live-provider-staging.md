# ADR 0022: Live-provider staging is manual, budgeted and exactly reconciled

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
reconciliation must remain separate.

GitHub environment configuration is external operational state. Repository files
can name an environment and reference a secret, but they cannot prove that the
environment exists, that reviewers or branch restrictions are configured, or
that the secret is present and current.

GitHub additionally requires a workflow configured with `workflow_dispatch` to
exist on the repository default branch before it can be manually dispatched.
The Phase 1.9 workflow currently exists only on PR #70, while the default branch
is `main`. Therefore the code boundary can be validated before merge, but a live
acceptance run is operationally blocked until an explicitly reviewed
bootstrap/default-branch strategy is established.

## Decision

1. Live staging remains validation-only and disabled for ordinary Core runtime.
2. The only live entry is `.github/workflows/live-provider-staging.yml` using
   `workflow_dispatch`; push, pull-request, schedule and runtime API triggers are
   forbidden.
3. The live job references the protected environment
   `live-provider-staging`. `AVALAI_API_KEY` is an environment secret and is not
   a repository file, Android value, task field, artifact field or ordinary-CI
   secret.
4. A live run requires separate explicit user approval bound to the exact
   lowercase 40-character commit SHA, selected ref, reviewed model and maximum
   spend. Prior conversational approval or approval of another SHA is invalid.
5. The reviewed model allowlist initially contains only `gpt-5.4-mini`.
6. The request uses fixed Core-authored canary input and output contracts. User,
   conversation, repository and project content are forbidden.
7. Simorgh permits exactly one model call, zero retries, zero tools, zero
   connector calls, zero failover and one parallel branch.
8. The reviewed hard ceilings are 128 input tokens, 16 output tokens,
   20,000 micro-USD estimated cost, 0.01 `UNIT` exact cost, a 0.10 `UNIT`
   remaining-credit floor and 60,000 ms elapsed time.
9. The canary traverses the existing `AgentTaskControlPlane`,
   `BudgetedModelGateway`, durable `InvocationStore`, correlated Trace and
   staging-result authority. GitHub Actions and the CLI do not create substitute
   authority.
10. Invocation identity is durably claimed and worst-case usage is reserved
    before provider entry. Uncertain entry becomes durable `unknown`; it never
    causes an automatic second model request.
11. After provider completion, only the AvalAI User API transaction lookup for
    the captured provider request ID may be polled. Polling is bounded to six
    attempts separated by 5,000 ms and cannot invoke the model.
12. Phase 1.9 acceptance requires exact transaction identity, provider, model,
    successful status, non-streaming behavior, token usage and exact cost under
    the ceiling. `pending` or `unavailable` reconciliation is incomplete and is
    never interpreted as zero cost.
13. Billing reconciliation is audit evidence. It cannot rewrite completed or
    uncertain Invocation truth, release committed budget or manufacture success.
14. Exact replay uses the same staging, request and invocation identities and
    must add zero provider, catalog, credit or transaction calls and zero usage.
15. The uploaded artifact is a strict versioned sanitized authority. It contains
    bounded IDs, counters, usage, reconciliation and Trace evidence, but no
    prompt, output text, credential, header, IP address, API-key suffix, cookie,
    raw provider/User API body or environment dump.
16. Repository evidence and external operational configuration are reported
    separately. Missing environment/reviewer/secret evidence remains
    `UNVERIFIED`; it is never inferred from workflow YAML.
17. A live run is forbidden while the workflow is absent from the default
    branch. No push trigger, temporary schedule, generic script, REST bypass or
    weaker secret scope may be introduced to evade this GitHub requirement.
18. Ordinary CI remains fake and zero-external. Full Core and Android gates must
    be green on the exact reviewed Head before any live approval.

## Operational approval record

The approval record must name all of the following:

```text
exact commit SHA
exact selected ref
model ID = gpt-5.4-mini
max model calls = 1
max input tokens = 128
max output tokens = 16
max estimated cost = 20000 micro-USD
max exact cost = 0.01 UNIT
approval time and approving user
```

Changing any field invalidates approval and requires a new review.

## Consequences

### Positive

- live cost and provider entry remain bounded and reviewable;
- uncertain provider entry is honest and cannot trigger duplicate execution;
- billing evidence is exact without becoming execution authority;
- replay can prove zero duplicate calls and usage;
- credentials remain behind GitHub environment protection;
- artifact privacy is enforced by schema, hash and forbidden-marker scanning;
- operational unknowns are explicit rather than implied by repository code.

### Costs

- the first accepted run requires external environment setup and human approval;
- default-branch `workflow_dispatch` requirements create a bootstrap sequencing
  problem before PR #70 can satisfy its live merge gate;
- exact reconciliation may require waiting or a later User API-only lookup;
- another artifact and operational incident procedure must be retained;
- GitHub plan, repository visibility and environment settings affect available
  protection rules and must be checked operationally.

## Rejected alternatives

### Run the canary from ordinary CI

Rejected because ordinary pushes and pull requests must remain zero-external and
must not access provider credentials.

### Store the key as a repository or organization secret

Rejected because the key must be scoped to the protected staging job and remain
unavailable before environment approval.

### Call AvalAI from a standalone script

Rejected because it would bypass Task, budget, Invocation, Trace, replay and
uncertainty authorities.

### Retry the model after timeout, cancellation or missing transaction data

Rejected because provider entry may already have occurred. Only the same
transaction ID may be queried through the User API.

### Accept pending reconciliation

Rejected because pending or unavailable billing evidence is incomplete, not zero
cost and not a Phase 1.9 merge acceptance.

### Upload raw prompt, output or HTTP bodies for debugging

Rejected because workflow artifacts and logs are durable disclosure surfaces.
Typed hashes, counts and reconciliation codes are sufficient.

### Infer environment readiness from workflow YAML

Rejected because naming an environment or secret does not prove its GitHub
configuration or current provider validity.

### Add a temporary push trigger to bypass default-branch dispatchability

Rejected because it would open an automatic paid execution path and violate the
issue's core trust boundary.

## Follow-up

- use `docs/LIVE_PROVIDER_STAGING_RUNBOOK.md` for setup, dispatch and incidents;
- use `docs/validation/phase-1-9-protected-environment-readiness.md` for the
  current evidence audit;
- use `docs/validation/phase-1-9-live-acceptance-checklist.md` for exact approval
  and run acceptance;
- resolve the default-branch workflow bootstrap sequencing in a separately
  reviewed, zero-live-call increment;
- configure and independently verify the protected environment and secret;
- obtain explicit user approval for exact SHA, ref, model and spend;
- execute one canary, obtain exact reconciliation and prove zero-call replay;
- complete review audit and merge Phase 1.9 before beginning Phase 1.10.
