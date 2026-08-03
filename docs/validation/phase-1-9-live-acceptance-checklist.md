# Phase 1.9 live-acceptance checklist

Status: **NOT READY — do not dispatch**

This checklist authorizes at most one manually approved AvalAI canary after all
blocking readiness items are satisfied. Checking a box is an operator assertion
that must be backed by current evidence. Do not pre-check or infer external
GitHub/provider settings.

## Fixed reviewed limits

```text
workflow: .github/workflows/live-provider-staging.yml
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

Any changed value requires a new reviewed commit, full CI and explicit approval.

## A. Repository and code review

- [ ] Record the exact lowercase 40-character commit SHA:

  ```text
  approved_commit_sha: ________________________________________
  ```

- [ ] Record the exact selected branch or tag:

  ```text
  approved_ref: ________________________________________________
  ```

- [ ] `git rev-parse <approved_ref>` equals `approved_commit_sha`.
- [ ] The workflow definition is present on the repository default branch and
  GitHub exposes the manual **Run workflow** control.
- [ ] The selected ref contains the same reviewed workflow controls.
- [ ] PR #70 changed-file audit is complete.
- [ ] PR comments, review submissions and inline review threads are empty or all
  required actions are resolved.
- [ ] Core and Android CI are green on the exact approved tree.
- [ ] No unreviewed change exists after the CI run.
- [ ] Ordinary CI remains zero-external and does not reference `AVALAI_API_KEY`.

**Current audit result:** the default-branch workflow requirement is not yet
satisfied. Section A cannot currently pass.

## B. Protected GitHub environment

- [ ] Environment `live-provider-staging` exists.
- [ ] At least one independent required reviewer is configured.
- [ ] Prevention of self-review is enabled when available.
- [ ] Deployment branches/tags use a selected allowlist, not unrestricted access.
- [ ] The exact approved ref matches the configured deployment restriction.
- [ ] Environment secret `AVALAI_API_KEY` is present and has a current update
  timestamp.
- [ ] The key is not supplied by a repository file, workflow input or Android.
- [ ] No repository/organization secret is relied upon as a weaker fallback.
- [ ] The workflow is enabled in GitHub Actions.
- [ ] No other live-provider workflow run is queued, awaiting approval or active.

Evidence record:

```text
environment_verified_by: ______________________________________
environment_verified_at_utc: __________________________________
required_reviewer: _____________________________________________
self_review_prevention: enabled / unavailable / not_enabled
deployment_ref_rule: ___________________________________________
environment_secret_name: AVALAI_API_KEY
environment_secret_updated_at: _________________________________
workflow_enabled_verified: yes / no
```

Do not record or screenshot the secret value.

## C. Explicit user approval

Approval must be given after Sections A and B are complete and must state the
exact values below.

```text
approved_by_user: ______________________________________________
approved_at_utc: _______________________________________________
approved_commit_sha: ___________________________________________
approved_ref: __________________________________________________
approved_model_id: gpt-5.4-mini
approved_max_model_calls: 1
approved_max_input_tokens: 128
approved_max_output_tokens: 16
approved_max_estimated_cost_microusd: 20000
approved_max_exact_cost_unit: 0.01 UNIT
```

- [ ] The approval explicitly permits one live AvalAI model request.
- [ ] The approval is not inferred from implementation, CI, an old message or a
  different commit.
- [ ] The required environment reviewer is not relying solely on self-approval.

## D. Dispatch form verification

- [ ] Open **Actions -> Phase 1.9 Live Provider Staging -> Run workflow**.
- [ ] Select exactly `approved_ref`.
- [ ] Enter exactly `approved_commit_sha` as `reviewed_commit_sha`.
- [ ] Keep `model_id` equal to `gpt-5.4-mini`.
- [ ] Compare all form values with Section C.
- [ ] Confirm no second run is active.
- [ ] Start the workflow once.

Run record:

```text
workflow_run_id: _______________________________________________
workflow_run_number: ___________________________________________
dispatch_actor: ________________________________________________
dispatch_time_utc: _____________________________________________
environment_reviewer: __________________________________________
environment_approval_time_utc: _________________________________
```

## E. Pre-secret and environment gates

- [ ] Exact SHA checkout validation passes.
- [ ] Ruff passes.
- [ ] Strict MyPy passes.
- [ ] Targeted fake staging tests pass.
- [ ] The live job waits for the protected environment.
- [ ] The independent reviewer compares the pending deployment to this checklist.
- [ ] The reviewer rejects the deployment if SHA, ref, model or workflow differs.
- [ ] `AVALAI_API_KEY` remains unavailable to the pre-secret job.

Any failure before environment approval must result in zero provider calls.

## F. Required live artifact evidence

Acceptance requires every item below:

- [ ] Artifact disposition is `passed`.
- [ ] Staging disposition is `completed`.
- [ ] Invocation state is `completed`.
- [ ] Reconciliation disposition is `exact`.
- [ ] Provider request ID is present and valid.
- [ ] Exact transaction ID equals the retained provider request ID.
- [ ] Provider is `openai` in the reviewed AvalAI transaction projection.
- [ ] Model is exactly `gpt-5.4-mini`.
- [ ] Transaction status is successful.
- [ ] Transaction is non-streaming.
- [ ] Transaction token usage matches durable Invocation usage.
- [ ] Exact cost is at or below `0.01 UNIT`.
- [ ] Local worst-case estimate is at or below `20000` micro-USD.
- [ ] First-run model generation count is exactly `1`.
- [ ] First-run model catalog count is exactly `1`.
- [ ] First-run credit lookup count is exactly `1`.
- [ ] At least one and no more than six transaction lookups occurred.
- [ ] Replay provider, catalog, credit and transaction deltas are all zero.
- [ ] Committed usage is unchanged by replay.
- [ ] Request, Invocation, Trace and terminal-event identities correlate.
- [ ] Artifact schema, canonical SHA-256, deterministic ID and privacy scan pass.
- [ ] Workflow logs and artifact contain no credential/private marker.

`pending`, `unavailable`, `mismatch`, `unknown`, missing transaction or failed
artifact verification are **not accepted**.

## G. Stop and incident conditions

Stop acceptance and do not issue another model request when any condition occurs:

- [ ] provider entry or completion is uncertain;
- [ ] the workflow is cancelled after durable reservation;
- [ ] provider request ID is missing or invalid;
- [ ] transaction remains pending/unavailable after the bounded window;
- [ ] provider/model/status/stream/usage/cost identity mismatches;
- [ ] exact cost exceeds the ceiling;
- [ ] artifact privacy/hash/schema verification fails;
- [ ] duplicate charge is suspected;
- [ ] credential leakage is suspected;
- [ ] environment protection was bypassed or self-approved contrary to policy.

Required response:

```text
disable workflow
cancel/reject pending work when safe
preserve durable Invocation and Trace evidence
do not retry the model
query only the same provider request ID through the User API
rotate the credential when leakage is possible
record the incident without private values
```

## H. Post-run evidence

```text
source_commit_sha: _____________________________________________
selected_ref: __________________________________________________
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
- [ ] Record artifact ID and digest, never the key or raw body.
- [ ] Confirm no second provider request was issued.
- [ ] Keep PR #70 unmerged until exact reconciliation and replay evidence satisfy
  every acceptance item.
