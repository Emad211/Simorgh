# Live Provider Staging operator runbook

Status: operational candidate for Phase 1.9. No live run is authorized by this
document.

## Purpose

This runbook configures, reviews, executes and investigates the single manually
approved AvalAI staging canary defined by:

- issue #65;
- ADR 0022;
- `.github/workflows/live-provider-staging-dispatch.yml`;
- `.github/workflows/live-provider-staging.yml`;
- `services/core/src/simorgh_core/agents/live_provider_staging_cli.py`.

It does not enable ordinary Core model traffic, scheduled validation, a public
endpoint or an automatic retry path.

Official GitHub references:

- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow
- https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations
- https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows
- https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments
- https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/cancel-a-workflow-run

## Reviewed topology

| Boundary | Reviewed value |
|---|---|
| Manual dispatcher | `.github/workflows/live-provider-staging-dispatch.yml` |
| Dispatcher trigger | `workflow_dispatch` only |
| Dispatcher ref | `refs/heads/main` only |
| Dispatcher input | `approved_dispatcher_sha` only |
| Reusable worker | `.github/workflows/live-provider-staging.yml` |
| Worker trigger | `workflow_call` only |
| Worker reference | exact full 40-character commit SHA |
| Worker model input | hardcoded `gpt-5.4-mini` from dispatcher |
| Secrets passed by dispatcher | none |
| Environment | `live-provider-staging` |
| Environment secret | `AVALAI_API_KEY` |

The dispatcher pins both the reusable-worker `uses` reference and
`reviewed_commit_sha` to the same exact commit. The operator cannot select a
worker SHA or model in the dispatch form.

## Reviewed execution constants

| Control | Reviewed value |
|---|---|
| Provider | `avalai` |
| API base URL | `https://api.avalai.ir/v1` |
| User API base URL | `https://api.avalai.ir/user/v1` |
| Model | `gpt-5.4-mini` |
| Model calls | `1` |
| Retries | `0` |
| Parallel branches | `1` |
| Input-token ceiling | `128` |
| Output-token ceiling | `16` |
| Estimated-cost ceiling | `20000` micro-USD |
| Exact-cost ceiling | `0.01 UNIT` |
| Remaining-credit floor | `0.10 UNIT` |
| Elapsed-time ceiling | `60000 ms` |
| Transaction lookup | `6` attempts, `5000 ms` interval |
| User API timeout | `10000 ms` |
| User API response ceiling | `256000` bytes |
| Sanitized artifact retention | `30` days |

A change to any reviewed value, either workflow path or either pinned SHA
requires code review, static tests, full CI and a new explicit user approval.

## Why the two-file topology exists

GitHub accepts `workflow_dispatch` only when the workflow file exists on the
default branch. Simorgh therefore uses:

```text
main: live-provider-staging-dispatch.yml
  workflow_dispatch
  -> validate exact main dispatcher SHA
  -> call exact worker SHA with fixed model and no secrets

reviewed worker commit: live-provider-staging.yml
  workflow_call
  -> validate caller repository/ref/workflow path
  -> checkout exact worker SHA
  -> fake pre-secret gates
  -> protected environment
  -> one governed canary
```

This avoids merging the complete unaccepted Phase 1.9 implementation merely to
make the manual button visible. It also avoids copying runtime logic into `main`.

## Zero-live-call bootstrap procedure

This procedure makes the dispatcher available on `main`; it never authorizes or
starts a canary.

1. Freeze a reviewed worker commit containing the reusable workflow and native
   staging implementation.
2. Create `.github/workflows/live-provider-staging-dispatch.yml` with:
   - `workflow_dispatch` only;
   - one required `approved_dispatcher_sha` string input;
   - `contents: read` permissions;
   - ref/repository/SHA validation before the reusable call;
   - exact worker SHA in both `jobs.<id>.uses` and
     `with.reviewed_commit_sha`;
   - fixed `model_id: gpt-5.4-mini`;
   - no `secrets` or `secrets: inherit` entry.
3. Open a separate bootstrap PR targeting `main`. Keep its product diff limited
   to the dispatcher file.
4. Verify ordinary Core and Android CI on the bootstrap PR.
5. Compare the bootstrap file blob with the reviewed copy validated in PR #70.
6. Merge the bootstrap PR without dispatching it.
7. Record the resulting exact `main` SHA and confirm the manual workflow is
   visible/enabled. Do not press **Run workflow**.
8. Re-run the protected-environment readiness audit.

The bootstrap merge changes dispatchability only. It does not prove environment,
reviewer, secret, provider credit or live acceptance readiness.

## Roles

- **Operator** — prepares the exact run, confirms repository and environment
  evidence, starts the manual dispatcher and preserves evidence.
- **Required reviewer** — independently compares the pending environment job with
  the approved checklist before permitting credential access.
- **Approving user** — explicitly approves both exact SHAs, `refs/heads/main`,
  model and hard maximum spend. This approval cannot be delegated to a model or
  inferred from earlier discussion.

For a one-person repository, enable prevention of self-review and use an
independent trusted reviewer when the feature is available. If independent
review cannot be configured, record that limitation and do not claim a protected
human-approval boundary.

## One-time GitHub environment setup

Repository administrators perform these steps in GitHub's web UI.

1. Open repository **Settings -> Environments**.
2. Create an environment named exactly `live-provider-staging`.
3. Configure at least one independent required reviewer.
4. Enable prevention of self-review when available.
5. Configure **Deployment branches and tags** as a selected allowlist.
6. Permit only `main` for the approved dispatcher topology. The reusable worker
   sees the caller's `github.ref`, which must remain `refs/heads/main`.
7. Add environment secret `AVALAI_API_KEY`.
8. Do not duplicate the provider credential as a repository secret,
   organization secret, Actions variable, committed `.env` value or Android
   secret.
9. Record the configuration date and reviewer identity without recording the
   secret value.
10. Confirm repository Actions policy permits the pinned actions and same-repo
    reusable workflow reference.

Environment secrets become available only to the worker job that references the
environment and, when approval is required, only after approval. The dispatcher
passes no secrets.

## Credential setup and handling

1. Create a dedicated AvalAI credential for staging when provider account controls
   permit it.
2. Restrict or label the credential for this purpose where supported.
3. Copy the value directly into the GitHub environment-secret form.
4. Clear clipboard history and local scratch files after entry.
5. Never paste the value into an issue, PR, workflow input, log, artifact,
   screenshot, shell history or chat.
6. Verify only that GitHub displays the secret name and update timestamp.
7. Confirm activity and account credit through the reviewed preflight, not by
   logging raw account responses.

## Pre-dispatch review

Complete `docs/validation/phase-1-9-live-acceptance-checklist.md` before opening
the Actions form.

Required repository evidence:

- exact lowercase 40-character dispatcher SHA currently on `main`;
- exact lowercase 40-character reusable worker SHA pinned in the dispatcher;
- the `main` dispatcher blob is identical to the reviewed PR #70 copy;
- `jobs.<id>.uses` and `with.reviewed_commit_sha` contain the same worker SHA;
- fixed model remains `gpt-5.4-mini`;
- PR #70 changed-file and review-thread audit is complete;
- green Core and Android CI on the exact worker tree;
- green Core and Android CI on the bootstrap dispatcher tree;
- no unreviewed change after either CI run;
- ordinary CI remains zero-external.

Required operational evidence:

- environment exists with the exact name;
- reviewer protection and self-review policy are recorded;
- deployment restriction permits only `main`;
- environment secret name is present and current;
- explicit user approval states both SHAs, ref, model and maximum spend;
- no live-provider run is queued, awaiting approval, active or unresolved.

Stop immediately if any field is missing, stale, contradictory or assumed.

## Manual dispatch

This procedure is valid only after the dispatcher bootstrap is merged and all
checklist prerequisites are complete.

1. Open **Actions** in the Simorgh repository.
2. Select **Phase 1.9 Live Provider Staging Dispatcher**.
3. Select **Run workflow**.
4. Select branch `main` only.
5. Enter the exact approved current `main` SHA as
   `approved_dispatcher_sha`.
6. Confirm the form exposes no worker SHA, model, prompt, budget or provider
   input.
7. Compare the current dispatcher and pinned worker SHAs with the signed approval
   record.
8. Start the workflow once.
9. Do not start a second run while the first is queued, awaiting approval,
   running or unresolved.

The dispatcher first checks that repository/ref are exact and that the supplied
approval SHA equals `github.sha`. The worker then checks caller workflow identity,
model and exact checkout SHA. Any mismatch fails before environment-secret
access.

## Review and monitor the run

The expected sequence is:

```text
dispatcher.validate-dispatcher
  -> main/ref/repository/dispatcher-SHA checks
  -> reusable worker pinned by exact commit SHA
  -> worker.validate-reviewed-head
  -> exact checkout/caller/model checks
  -> dependency installation
  -> Ruff, strict MyPy and fake acceptance
  -> worker.live-canary waits for environment approval
  -> required reviewer compares the pending job with the checklist
  -> one protected canary and exact local replay
  -> artifact verification
  -> sanitized artifact upload
```

The reviewer must reject the environment job when either SHA, ref, model,
workflow diff or checklist differs from approval.

A queued or in-progress run may be cancelled from GitHub Actions. Cancellation
after provider entry does not prove that no request or charge occurred. Do not
start a replacement model run until Invocation and transaction evidence establish
what happened.

## Artifact retrieval and verification

The worker uploads only `live-provider-staging-<run-id>` containing the sanitized
JSON artifact.

1. Download the artifact from the exact dispatcher run.
2. Preserve the original ZIP and record its GitHub artifact ID and digest.
3. Extract the JSON into an isolated working directory.
4. Verify locally using the exact worker source tree:

```bash
python -m simorgh_core.agents.live_provider_staging_cli verify \
  --artifact live-provider-staging.json \
  --require-passed
```

5. Do not edit and re-hash the artifact to make it pass.
6. Do not upload the artifact outside the approved evidence boundary.

## Interpreting results

### Accepted

All of the following are required:

- artifact disposition is `passed`;
- staging disposition is `completed`;
- reconciliation disposition is `exact`;
- invocation state is `completed`;
- provider request ID and exact transaction are present and identical;
- provider, model, status, stream, token and cost checks pass;
- exact cost is at or below `0.01 UNIT`;
- first-run model generation count is exactly one;
- replay external-call deltas are all zero;
- committed usage is unchanged by replay;
- artifact verification and forbidden-marker scan pass.

### Incomplete — not accepted

Any of these blocks Phase 1.9 acceptance:

- reconciliation `pending` or `unavailable`;
- staging disposition `incomplete`;
- missing transaction or provider request identity;
- failed artifact verification;
- absent Trace evidence;
- provider, model, status, stream, usage or cost mismatch.

A later attempt may query only the User API for the same provider request ID. It
must not repeat the model request.

### Unknown invocation

`unknown` means provider entry or completion could not be proven. Preserve the
conservative usage and all durable stores. Do not rerun the canary under a new
identity merely to obtain a clean result.

### Mismatch

A mismatch is evidence requiring investigation, not a recoverable warning. The
completed Invocation remains immutable and the staging run fails acceptance.

## Incident response

### Suspected duplicate charge

1. Disable the dispatcher immediately.
2. Do not start another model request.
3. Preserve the workflow run, artifact, request/invocation IDs and SQLite files.
4. Query only the AvalAI User API for the retained provider request ID.
5. Compare transaction IDs, timestamps, model, token usage and exact cost.
6. Escalate with bounded identifiers only.
7. Keep Phase 1.9 blocked until duplicate execution is disproved or resolved.

### Unknown invocation or cancelled run

1. Treat reserved/committed usage as authoritative and conservative.
2. Do not interpret cancellation as proof of non-entry.
3. Preserve Invocation and Trace authorities.
4. Perform only same-ID transaction reconciliation.
5. Do not dispatch a replacement without a separately reviewed recovery decision.

### Cost mismatch or ceiling exceeded

1. Disable the dispatcher.
2. Preserve the artifact and provider request ID.
3. Do not rewrite local committed usage or transaction evidence.
4. Compare reviewed pricing, provider model, transaction source/currency and token
   totals.
5. Do not increase ceilings or rerun until a reviewed policy change exists.

### Credential exposure or suspected leakage

1. Cancel queued/running work when safe.
2. Disable the dispatcher.
3. Revoke the AvalAI credential immediately.
4. Remove or replace the GitHub environment secret.
5. Preserve a sanitized incident record.
6. Review GitHub access, workflow history and provider transactions.
7. Create a new credential and follow rotation.
8. Do not re-enable staging until the leak path is closed and fake CI is green.

### Artifact privacy failure

1. Treat the run as failed even if provider execution completed.
2. Disable the dispatcher and prevent artifact sharing.
3. Delete exposed artifacts after retaining safe incident metadata.
4. Rotate the key when credential exposure cannot be excluded.
5. Fix schema/scanner coverage using fake tests only until separately approved.

## Credential rotation

1. Disable `live-provider-staging-dispatch.yml` in GitHub Actions.
2. Create a new dedicated AvalAI key.
3. Replace environment secret `AVALAI_API_KEY` without exposing its value.
4. Revoke the old key.
5. Verify environment protection and the `main` restriction again.
6. Run ordinary fake Core/Android CI only.
7. Obtain a new explicit approval before any subsequent live canary.

Rotation never authorizes a live request by itself.

## Emergency disablement

```bash
gh workflow disable live-provider-staging-dispatch.yml
gh run cancel <RUN_ID>
```

Web UI equivalents:

- Actions -> Phase 1.9 Live Provider Staging Dispatcher -> menu -> Disable
  workflow;
- open a queued/in-progress run -> Cancel workflow;
- Settings -> Environments -> live-provider-staging -> remove or replace the
  environment secret;
- reject a pending environment deployment.

The worker has no direct manual trigger. Disabling the dispatcher closes the
reviewed manual entry. Disabling or cancelling does not reverse a provider
request that may already have entered.

## Post-run evidence record

Record in `docs/DEVELOPMENT_HANDOFF.md` and issue #65:

- exact dispatcher SHA and `refs/heads/main`;
- exact pinned worker SHA;
- approving user and approval timestamp;
- workflow run number and ID;
- environment reviewer identity;
- artifact ID and digest;
- staging/request/invocation/provider request IDs;
- Invocation and reconciliation dispositions;
- local committed usage and exact transaction cost;
- first-run and replay call counts;
- privacy verification result;
- any incident, limitation or unverified assumption.

Never record the provider credential, raw output, raw HTTP body, IP address,
API-key suffix, cookie, authorization header or full environment dump.

## Current limitations

- environment, reviewer and secret configuration cannot be proven by repository
  contents alone;
- the current connector surface does not expose those settings;
- bootstrap merge alone does not authorize dispatch;
- no real canary or transaction artifact exists yet;
- a pending transaction does not satisfy the Phase 1.9 merge gate;
- Phase 1.10 remains blocked until Phase 1.9 is accepted and merged.
