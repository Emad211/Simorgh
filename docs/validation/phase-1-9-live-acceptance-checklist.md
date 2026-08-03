# Phase 1.9 live-acceptance checklist

Status: **NOT READY — do not dispatch**

This checklist authorizes at most one manually approved AvalAI canary after all
blocking readiness items are satisfied. Checking a box is an operator assertion
backed by current evidence. Do not pre-check external GitHub/provider settings.

## Fixed reviewed topology and limits

```text
dispatcher_workflow: .github/workflows/live-provider-staging-dispatch.yml
dispatcher_trigger: workflow_dispatch only
dispatcher_ref: refs/heads/main
dispatcher_input: approved_dispatcher_sha only
worker_workflow: .github/workflows/live-provider-staging.yml
worker_trigger: workflow_call only
worker_reference: exact full commit SHA
worker_sha_is_dispatch_input: false
model_is_dispatch_input: false
secrets_forwarded_by_dispatcher: false
environment: live-provider-staging
secret_name: AVALAI_API_KEY
provider_id: avalai
api_base_url: https://api.avalai.ir/v1
user_api_base_url: https://api.avalai.ir/user/v1
model_id: gpt-5.4-mini
max_model_calls: 1
max_retries: 0
max_parallel_branches: 1
max_input_tokens: 128
max_output_tokens: 16
max_estimated_cost_microusd: 20000
max_exact_cost_unit: 0.01 UNIT
minimum_credit_floor_unit: 0.10 UNIT
max_elapsed_ms: 60000
transaction_poll_attempts: 6
transaction_poll_interval_ms: 5000
user_api_timeout_ms: 10000
user_api_max_response_bytes: 256000
artifact_retention_days: 30
```

Any changed path, SHA or value requires a new reviewed commit, full CI and
explicit approval.

## A. Bootstrap and repository evidence

- [ ] Record the exact lowercase 40-character dispatcher SHA currently on
  `main`:

  ```text
  approved_dispatcher_sha: _____________________________________
  ```

- [ ] Record the exact lowercase 40-character reusable worker SHA:

  ```text
  approved_worker_sha: _________________________________________
  ```

- [ ] Record the exact dispatcher ref:

  ```text
  approved_ref: refs/heads/main
  ```

- [ ] `git rev-parse main` equals `approved_dispatcher_sha`.
- [ ] The dispatcher file is present on `main` and GitHub exposes **Run
  workflow** without starting a run.
- [ ] The dispatcher was merged through a separate bootstrap PR whose product
  diff contains only the dispatcher file.
- [ ] Bootstrap Core and Android CI are green.
- [ ] The dispatcher file on `main` is byte-identical to the reviewed PR #70
  copy.
- [ ] Dispatcher `jobs.<id>.uses` references the worker using
  `@approved_worker_sha`.
- [ ] Dispatcher `with.reviewed_commit_sha` equals `approved_worker_sha`.
- [ ] Dispatcher hardcodes `model_id: gpt-5.4-mini`.
- [ ] Dispatcher exposes no worker SHA, model, provider, prompt or budget input.
- [ ] Dispatcher contains no `secrets` or `secrets: inherit` entry.
- [ ] Dispatcher validates repository `Emad211/Simorgh`, ref
  `refs/heads/main` and `approved_dispatcher_sha == github.sha`.
- [ ] Worker is `workflow_call` only and validates caller repository/ref/workflow
  path, exact checkout SHA and fixed model.
- [ ] PR #70 changed-file audit is complete.
- [ ] PR comments, review submissions and inline threads are empty or resolved.
- [ ] Core and Android CI are green on the exact worker tree.
- [ ] No unreviewed change exists after either CI run.
- [ ] Ordinary CI remains zero-external and does not reference
  `AVALAI_API_KEY`.

**Current audit result:** Section A remains incomplete until bootstrap merge and
final exact-SHA evidence are recorded.

## B. Protected GitHub environment

- [ ] Environment `live-provider-staging` exists.
- [ ] At least one independent required reviewer is configured.
- [ ] Prevention of self-review is enabled when available.
- [ ] Deployment branches/tags use a selected allowlist.
- [ ] The allowlist permits only `main` for this topology.
- [ ] Environment secret `AVALAI_API_KEY` is present and current.
- [ ] The key is not supplied by a repository file, workflow input or Android.
- [ ] No repository/organization secret is relied upon as fallback.
- [ ] The dispatcher workflow is enabled in GitHub Actions.
- [ ] No other live-provider run is queued, awaiting approval, active or
  unresolved.

Evidence record:

```text
environment_verified_by: ______________________________________
environment_verified_at_utc: __________________________________
required_reviewer: _____________________________________________
self_review_prevention: enabled / unavailable / not_enabled
deployment_ref_rule: main only / _______________________________
environment_secret_name: AVALAI_API_KEY
environment_secret_updated_at: _________________________________
dispatcher_enabled_verified: yes / no
```

Do not record or screenshot the secret value.

## C. Explicit user approval

Approval must be given after Sections A and B are complete and must state every
exact value below.

```text
approved_by_user: ______________________________________________
approved_at_utc: _______________________________________________
approved_dispatcher_sha: _______________________________________
approved_worker_sha: ___________________________________________
approved_ref: refs/heads/main
approved_model_id: gpt-5.4-mini
approved_max_model_calls: 1
approved_max_input_tokens: 128
approved_max_output_tokens: 16
approved_max_estimated_cost_microusd: 20000
approved_max_exact_cost_unit: 0.01 UNIT
```

- [ ] Approval explicitly permits one live AvalAI model request.
- [ ] Approval is not inferred from implementation, CI, bootstrap merge, an old
  message or different SHA.
- [ ] Required environment reviewer is not relying solely on self-approval.

## D. Dispatcher form verification

- [ ] Open **Actions -> Phase 1.9 Live Provider Staging Dispatcher -> Run
  workflow**.
- [ ] Select branch `main` only.
- [ ] Enter exactly `approved_dispatcher_sha`.
- [ ] Confirm the form exposes no worker SHA or model field.
- [ ] Re-read the pinned worker SHA from the current dispatcher and compare it to
  Section C.
- [ ] Confirm no second run is active.
- [ ] Start the dispatcher once.

Run record:

```text
workflow_run_id: _______________________________________________
workflow_run_number: ___________________________________________
dispatch_actor: ________________________________________________
dispatch_time_utc: _____________________________________________
environment_reviewer: __________________________________________
environment_approval_time_utc: _________________________________
```

## E. Pre-secret, reusable-worker and environment gates

- [ ] Dispatcher repository/ref/SHA validation passes.
- [ ] Reusable worker was loaded from `approved_worker_sha`.
- [ ] Worker caller workflow-ref validation passes.
- [ ] Worker exact SHA checkout validation passes.
- [ ] Worker fixed-model validation passes.
- [ ] Ruff passes.
- [ ] Strict MyPy passes.
- [ ] Targeted fake staging tests pass.
- [ ] The live worker job waits for the protected environment.
- [ ] Independent reviewer compares both SHAs and limits to this checklist.
- [ ] Reviewer rejects if SHA, ref, model or workflow differs.
- [ ] `AVALAI_API_KEY` remains unavailable to dispatcher and pre-secret worker
  job.

Any failure before environment approval must result in zero provider calls.

## F. Required live artifact evidence

Acceptance requires every item below:

- [ ] Artifact disposition is `passed`.
- [ ] Staging disposition is `completed`.
- [ ] Invocation state is `completed`.
- [ ] Reconciliation disposition is `exact`.
- [ ] Provider request ID is present and valid.
- [ ] Exact transaction ID equals retained provider request ID.
- [ ] Provider is `openai` in reviewed AvalAI transaction projection.
- [ ] Model is exactly `gpt-5.4-mini`.
- [ ] Transaction status is successful.
- [ ] Transaction is non-streaming.
- [ ] Transaction token usage matches durable Invocation usage.
- [ ] Exact cost is at or below `0.01 UNIT`.
- [ ] Local worst-case estimate is at or below `20000` micro-USD.
- [ ] First-run model generation count is exactly `1`.
- [ ] First-run model catalog count is exactly `1`.
- [ ] First-run credit lookup count is exactly `1`.
- [ ] Between one and six transaction lookups occurred.
- [ ] Replay provider, catalog, credit and transaction deltas are zero.
- [ ] Committed usage is unchanged by replay.
- [ ] Request, Invocation, Trace and terminal-event identities correlate.
- [ ] Artifact schema, canonical SHA-256, deterministic ID and privacy scan pass.
- [ ] Workflow logs and artifact contain no credential/private marker.

`pending`, `unavailable`, `mismatch`, `unknown`, missing transaction or failed
artifact verification are **not accepted**.

## G. Stop and incident conditions

Stop acceptance and do not issue another model request when any condition occurs:

- [ ] dispatcher SHA or ref differs from approval;
- [ ] pinned worker SHA or model differs from approval;
- [ ] provider entry or completion is uncertain;
- [ ] workflow is cancelled after durable reservation;
- [ ] provider request ID is missing or invalid;
- [ ] transaction remains pending/unavailable after bounded lookup;
- [ ] provider/model/status/stream/usage/cost identity mismatches;
- [ ] exact cost exceeds ceiling;
- [ ] artifact privacy/hash/schema verification fails;
- [ ] duplicate charge is suspected;
- [ ] credential leakage is suspected;
- [ ] environment protection was bypassed or improperly self-approved.

Required response:

```text
disable dispatcher
cancel/reject pending work when safe
preserve durable Invocation and Trace evidence
do not issue another model request
query only the same provider request ID through the User API
rotate the credential when leakage is possible
record the incident without private values
```

## H. Post-run evidence

```text
dispatcher_commit_sha: _________________________________________
worker_commit_sha: _____________________________________________
selected_ref: refs/heads/main
workflow_run_id: _______________________________________________
workflow_run_number: ___________________________________________
artifact_id: ___________________________________________________
artifact_sha256: _______________________________________________
staging_run_id: ________________________________________________
request_id: ____________________________________________________
invocation_id: _________________________________________________
trace_id: ______________________________________________________
terminal_event_id: _____________________________________________
provider_request_id: ___________________________________________
invocation_state: ______________________________________________
reconciliation_disposition: ____________________________________
committed_usage: _______________________________________________
exact_cost_unit: _______________________________________________
replay_external_call_delta: ____________________________________
privacy_verification: passed / failed
incident_reference: none / _____________________________________
```

- [ ] Update `docs/DEVELOPMENT_HANDOFF.md`.
- [ ] Update issue #65 with sanitized evidence.
- [ ] Record artifact ID and digest, never key or raw body.
- [ ] Confirm no second provider request was issued.
- [ ] Keep PR #70 unmerged until exact reconciliation and replay evidence satisfy
  every acceptance item.
