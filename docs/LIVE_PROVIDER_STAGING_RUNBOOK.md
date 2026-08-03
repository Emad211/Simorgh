# Live Provider Staging operator runbook

Status: operational candidate for Phase 1.9. No live run is authorized by this
document.

## Purpose

This runbook configures, reviews, executes and investigates the single manually
approved AvalAI staging canary defined by:

- issue #65;
- ADR 0022;
- `.github/workflows/live-provider-staging.yml`;
- `services/core/src/simorgh_core/agents/live_provider_staging_cli.py`.

It does not enable ordinary Core model traffic, scheduled validation, a public
endpoint or an automatic retry path.

Official GitHub references:

- https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments
- https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/cancel-a-workflow-run

## Reviewed constants

| Control | Reviewed value |
|---|---|
| Workflow | `.github/workflows/live-provider-staging.yml` |
| Trigger | `workflow_dispatch` only |
| Environment | `live-provider-staging` |
| Environment secret | `AVALAI_API_KEY` |
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

A change to any reviewed value requires code review, static tests, full CI and a
new explicit user approval. Do not edit workflow inputs or environment variables
at dispatch time to widen these limits.

## Current operational block

GitHub exposes the **Run workflow** control only for a `workflow_dispatch`
workflow that exists on the repository default branch. Simorgh's default branch
is `main`, while the Phase 1.9 workflow is currently introduced by PR #70.

Therefore:

```text
implementation boundary: validated
manual dispatchability: blocked
live acceptance: not authorized
```

Do not bypass this block with a push trigger, schedule, generic REST call,
standalone provider script or a weaker workflow. A separately reviewed
bootstrap/default-branch strategy must be established first.

## Roles

- **Operator** — prepares the exact run, confirms repository and environment
  evidence, starts the manual workflow and preserves evidence.
- **Required reviewer** — independently compares the pending deployment with the
  approved checklist before permitting the environment job.
- **Approving user** — explicitly approves the exact commit, ref, model and hard
  maximum spend. This approval cannot be delegated to a model or inferred from
  earlier discussion.

For a one-person repository, enable GitHub's prevention of self-review and use an
independent trusted reviewer when the feature is available. If independent
review cannot be configured, record that limitation and do not claim a protected
human-approval boundary.

## One-time GitHub environment setup

Repository administrators perform these steps in GitHub's web UI. Wording may
change, but the resulting controls must remain equivalent.

1. Open the repository **Settings**.
2. Open **Environments**.
3. Create an environment named exactly `live-provider-staging`.
4. Configure **Required reviewers** with at least one independent trusted user or
   team.
5. Enable prevention of self-review when available.
6. Configure **Deployment branches and tags** as **Selected branches and tags**.
   Do not leave the environment unrestricted. Permit only the reviewed ref needed
   by the approved bootstrap/acceptance topology.
7. Add an **environment secret** named exactly `AVALAI_API_KEY`.
8. Do not duplicate the provider credential as a repository secret, organization
   secret, Actions variable, committed `.env` value or Android secret.
9. Record the environment configuration date and reviewer identity in the live
   acceptance checklist without recording the secret value.
10. Confirm repository Actions policy permits the exact pinned actions used by
    the workflow.

Environment secrets become available only to jobs that reference the environment
and, when approval is required, only after deployment approval. The repository
workflow cannot prove these settings; the operator must verify them in GitHub.

## Credential setup and handling

1. Create a dedicated AvalAI credential for staging when provider account controls
   permit it.
2. Restrict or label the credential for this purpose where supported.
3. Copy the value directly into the GitHub environment-secret form.
4. Clear clipboard history and local scratch files after entry.
5. Never paste the value into an issue, PR, workflow input, log, artifact,
   screenshot, shell history or chat.
6. Verify only that GitHub displays the secret **name** and an updated timestamp.
   Do not attempt to read the stored value back.
7. Confirm the key is active and the account has sufficient credit through the
   reviewed preflight, not by logging raw account responses.

## Pre-dispatch review

Complete `docs/validation/phase-1-9-live-acceptance-checklist.md` before opening
the Actions dispatch form.

Required repository evidence:

- exact lowercase 40-character commit SHA;
- exact selected ref and confirmation that it resolves to that SHA;
- PR #70 state and review-thread audit;
- green Core and Android CI on the exact reviewed tree;
- workflow available from the default branch without trigger widening;
- workflow enabled in GitHub Actions;
- no unreviewed change to workflow, policy, CLI, artifact or provider adapters.

Required operational evidence:

- environment exists with the exact name;
- reviewer protection and self-review policy are recorded;
- deployment branch/tag restriction matches the selected ref;
- environment secret name is present and current;
- explicit user approval states the exact SHA, ref, model and maximum spend;
- no other live-provider workflow is queued or running.

Stop immediately if any field is missing, stale, contradictory or merely
assumed.

## Manual dispatch

This procedure is valid only after the default-branch dispatchability blocker is
resolved and the checklist is approved.

1. Open **Actions** in the Simorgh repository.
2. Select **Phase 1.9 Live Provider Staging**.
3. Select **Run workflow**.
4. Select the exact approved ref.
5. Set `reviewed_commit_sha` to the exact approved 40-character SHA.
6. Keep `model_id` equal to `gpt-5.4-mini`.
7. Compare the form again with the signed approval record.
8. Start the workflow once.
9. Do not start a second run while the first is queued, awaiting approval,
   running or unresolved.

The workflow verifies that dispatch SHA, checkout SHA and the reviewed input SHA
are identical. A mismatch must fail before the secret boundary.

## Review and monitor the run

The expected sequence is:

```text
validate-reviewed-head
  -> exact checkout and SHA checks
  -> dependency installation
  -> Ruff, strict MyPy and fake acceptance
  -> live-canary waits for environment approval
  -> required reviewer compares the pending deployment with the checklist
  -> one protected canary and exact local replay
  -> artifact verification
  -> sanitized artifact upload
```

The reviewer must reject the deployment when the displayed ref, SHA, model,
workflow diff or checklist does not match approval.

A queued or in-progress run may be cancelled from GitHub Actions. Cancellation
after provider entry does not prove that no request or charge occurred. Never
start a replacement model run until Invocation and transaction evidence establish
what happened.

## Artifact retrieval and verification

The workflow uploads only `live-provider-staging-<run-id>` containing the
sanitized JSON artifact.

1. Download the artifact from the exact workflow run.
2. Preserve the original ZIP and record its GitHub artifact ID and digest.
3. Extract the JSON into an isolated working directory.
4. Verify locally using the exact reviewed source tree:

```bash
python -m simorgh_core.agents.live_provider_staging_cli verify \
  --artifact live-provider-staging.json \
  --require-passed
```

5. Do not edit and re-hash the artifact to make it pass.
6. Do not upload the artifact outside the approved repository evidence boundary.

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

A later attempt may query only the User API for the same provider request ID.
It must not repeat the model request.

### Unknown invocation

`unknown` means provider entry or completion could not be proven. Preserve the
conservative usage and all durable stores. Do not rerun the canary under a new
identity merely to obtain a clean result.

### Mismatch

A mismatch is evidence requiring investigation, not a recoverable warning. The
completed Invocation remains immutable and the staging run fails acceptance.

## Incident response

### Suspected duplicate charge

1. Disable the workflow immediately.
2. Do not start another model request.
3. Preserve the workflow run, artifact, request/invocation IDs and SQLite files.
4. Query only the AvalAI User API for the retained provider request ID.
5. Compare transaction IDs, timestamps, model, token usage and exact cost.
6. Escalate to the provider with bounded identifiers; never attach credentials,
   headers or raw private transaction bodies.
7. Keep Phase 1.9 blocked until duplicate execution is disproved or resolved.

### Unknown invocation or cancelled run

1. Treat the reserved/committed usage as authoritative and conservative.
2. Do not interpret cancellation as proof of non-entry.
3. Preserve Invocation and Trace authorities.
4. Perform only same-ID transaction reconciliation.
5. Do not dispatch a replacement canary without a separate reviewed recovery
   decision.

### Cost mismatch or ceiling exceeded

1. Disable the workflow.
2. Preserve the exact artifact and provider request ID.
3. Do not rewrite local committed usage or transaction evidence.
4. Compare reviewed pricing, provider model, transaction source/currency and token
   totals.
5. Do not increase ceilings or rerun until the discrepancy is understood and a
   new ADR/code review explicitly changes policy.

### Credential exposure or suspected leakage

1. Cancel queued/running work when safe to do so.
2. Disable the workflow.
3. Revoke the AvalAI credential immediately.
4. Remove or replace the GitHub environment secret.
5. Delete exposed artifacts/logs only after preserving an incident record that
   does not repeat the secret.
6. Review GitHub access, workflow history and provider transactions.
7. Create a new credential and follow the rotation procedure.
8. Do not re-enable live staging until the leak path is closed and full fake CI
   is green.

### Artifact privacy failure

1. Treat the run as failed even when the provider invocation completed.
2. Disable the workflow and prevent further artifact sharing.
3. Delete the exposed artifact after retaining safe metadata for incident review.
4. Rotate the provider key when credential exposure cannot be excluded.
5. Fix schema/scanner coverage and rerun only fake tests until separately approved.

## Credential rotation

1. Disable `live-provider-staging.yml` in GitHub Actions.
2. Create a new dedicated AvalAI key.
3. Replace the environment secret `AVALAI_API_KEY` without exposing its value.
4. Revoke the old key.
5. Verify environment protection and branch restrictions again.
6. Run ordinary fake Core/Android CI only.
7. Obtain a new explicit approval before any subsequent live canary.

Rotation never requires or authorizes a live validation request by itself.

## Emergency disablement

Use one or more of these controls:

```bash
gh workflow disable live-provider-staging.yml
gh run cancel <RUN_ID>
```

Web UI equivalents:

- Actions -> Phase 1.9 Live Provider Staging -> menu -> Disable workflow;
- open a queued/in-progress run -> Cancel workflow;
- Settings -> Environments -> live-provider-staging -> remove or replace the
  environment secret;
- reject a pending environment deployment.

Disabling or cancelling GitHub Actions does not reverse a provider request that
may already have entered. Preserve uncertainty and do not retry automatically.

## Post-run evidence record

Record in `docs/DEVELOPMENT_HANDOFF.md` and issue #65:

- exact source SHA and selected ref;
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
- the workflow is not manually dispatchable until its definition is present on
  the default branch;
- no real canary or transaction artifact exists yet;
- a pending transaction does not satisfy the Phase 1.9 merge gate;
- Phase 1.10 remains blocked until Phase 1.9 is accepted and merged.
