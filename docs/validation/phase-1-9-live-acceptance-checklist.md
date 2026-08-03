# Phase 1.9 live-acceptance checklist

Status: **NOT READY — DO NOT DISPATCH**

This checklist can authorize at most one manually approved AvalAI canary only
after every non-live prerequisite is proved and the user separately approves the
exact identity and hard spend limits. Repository implementation, CI, bootstrap
merge and this checklist are not live authorization.

## Current non-live evidence snapshot

```text
audit_timestamp: 2026-08-03T14:49+03:30
dispatcher_main_sha: 3bcb41437e3b8d2f497516ef9a214de5becf45e9
dispatcher_blob_sha: a5fe7be975ee41dd0be222ab1c606f8b4bab87d7
worker_sha: 47b65f359fd844067346d987f9102f6eeab911d9
pr_head_sha: 901e858e3be6d92d9a64e1617fdcf972dec4c2c9
merge_preview_sha: 6cb97ab7263bb17f11699159e28b49795d2a99ec
ci_run_id: 30803363635
ci_run_number: 1059
ci_result: success
core_tests: 575 passed
non_live_prerequisites_complete: false
approval_package_status: NOT PREPARED
live_dispatches: 0
deployment_approvals: 0
credentials_read_or_used: 0
real_provider_calls: 0
real_user_api_calls: 0
```

Repository, authenticated access and CI identity are verified. Workflow
state/visibility, Environment protection and Environment-secret metadata remain
`UNVERIFIED` because the authenticated Connector exposes no read endpoints for
those settings.

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

Any changed path, SHA or limit requires a new reviewed commit, full CI, a fresh
non-live audit and new explicit approval.

## A. Repository and bootstrap evidence

Current repository evidence has been recorded, but the operator must recheck it
immediately before requesting live approval.

- [ ] Record the current lowercase 40-character dispatcher SHA on `main`:

  ```text
  approved_dispatcher_sha: _____________________________________
  ```

- [ ] Record the reviewed reusable worker SHA:

  ```text
  approved_worker_sha: _________________________________________
  ```

- [ ] Record the exact dispatcher ref:

  ```text
  approved_ref: refs/heads/main
  ```

- [ ] `git rev-parse main` equals `approved_dispatcher_sha`.
- [ ] Dispatcher file exists on `main` with the reviewed blob SHA.
- [ ] The bootstrap PR product diff contains only the dispatcher file.
- [ ] Bootstrap Core and Android CI are green.
- [ ] Dispatcher `jobs.<id>.uses` references `@approved_worker_sha`.
- [ ] Dispatcher `with.reviewed_commit_sha` equals `approved_worker_sha`.
- [ ] Dispatcher hardcodes `model_id: gpt-5.4-mini`.
- [ ] Dispatcher exposes no worker SHA, model, provider, prompt or budget input.
- [ ] Dispatcher contains no `secrets` or `secrets: inherit` entry.
- [ ] Dispatcher verifies repository `Emad211/Simorgh`, ref
  `refs/heads/main` and `approved_dispatcher_sha == github.sha`.
- [ ] Worker is `workflow_call` only and validates caller repository/ref/workflow
  path, exact checkout SHA and fixed model.
- [ ] PR #70 changed-file audit is complete.
- [ ] PR comments, review submissions and inline threads are empty or resolved.
- [ ] Core and Android CI are green on the exact merge-preview.
- [ ] No unreviewed repository change exists after the recorded CI.
- [ ] Ordinary CI remains zero-external and does not reference
  `AVALAI_API_KEY`.

**Current audit result:** repository and CI evidence is verified as recorded in
`phase-1-9-protected-environment-readiness.md`, but Section A must be re-resolved
if `main`, PR #70, the worker or policy changes.

## B. Workflow and protected Environment metadata

No item in this section is currently proved by the authenticated Connector.

- [ ] Dispatcher is enabled and visible in GitHub Actions without starting it.
- [ ] Environment `live-provider-staging` exists.
- [ ] At least one independent required reviewer is configured.
- [ ] Prevention of self-review is enabled when available.
- [ ] Deployment branches/tags use a selected allowlist.
- [ ] The deployment allowlist permits only `main` for this topology.
- [ ] Environment secret `AVALAI_API_KEY` exists.
- [ ] Record the Environment-secret update timestamp without reading its value.
- [ ] The key is not supplied by a repository file, workflow input or Android.
- [ ] No repository/organization secret is relied upon as fallback.
- [ ] No other live-provider run is queued, awaiting approval, active or
  unresolved.

Evidence record:

```text
dispatcher_enabled_visible: UNVERIFIED
environment_exists: UNVERIFIED
environment_verified_by: ______________________________________
environment_verified_at_utc: __________________________________
required_reviewer: UNVERIFIED
independent_reviewer_identity: _________________________________
self_review_prevention: UNVERIFIED
deployment_ref_rule: UNVERIFIED
environment_secret_name: AVALAI_API_KEY
environment_secret_present: UNVERIFIED
environment_secret_updated_at: UNVERIFIED
weaker_secret_fallback_absent: UNVERIFIED
```

Never record, retrieve, print or screenshot the secret value.

**Current audit result:** Section B is incomplete. Approval package status remains
`NOT PREPARED`.

## C. Explicit user approval

This section must remain empty until Sections A and B are current and complete.
Approval must state every exact value below after the final non-live audit.

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
approved_minimum_credit_floor_unit: 0.10 UNIT
```

- [ ] Approval explicitly permits one live AvalAI model request.
- [ ] Approval is not inferred from implementation, CI, bootstrap merge, an old
  message or a different SHA.
- [ ] Required Environment reviewer is not relying solely on self-approval.

**Current audit result:** explicit user approval is `NOT GRANTED`.

## D. Dispatcher form verification

Do not open this section for execution until Sections A–C pass.

- [ ] Open **Actions -> Phase 1.9 Live Provider Staging Dispatcher -> Run
  workflow**.
- [ ] Select branch `main` only.
- [ ] Enter exactly `approved_dispatcher_sha`.
- [ ] Confirm the form exposes no worker SHA or model field.
- [ ] Re-read the pinned worker SHA from the current dispatcher and compare it to
  Section C.
- [ ] Confirm no second run is active or unresolved.
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

## E. Pre-secret, worker and Environment gates

- [ ] Dispatcher repository/ref/SHA validation passes.
- [ ] Reusable worker is loaded from `approved_worker_sha`.
- [ ] Worker caller workflow-ref validation passes.
- [ ] Worker exact SHA checkout validation passes.
- [ ] Worker fixed-model validation passes.
- [ ] Ruff passes.
- [ ] Strict MyPy passes.
- [ ] Targeted fake staging tests pass.
- [ ] Live worker waits for the protected Environment.
- [ ] Independent reviewer compares both SHAs and all limits to this checklist.
- [ ] Reviewer rejects if SHA, ref, model or workflow differs.
- [ ] `AVALAI_API_KEY` remains unavailable to the dispatcher and pre-secret job.

Any failure before Environment approval must result in zero provider calls.

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
- [ ] Environment protection was bypassed or improperly self-approved.

Required response:

```text
disable dispatcher
cancel or reject pending work when safe
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
