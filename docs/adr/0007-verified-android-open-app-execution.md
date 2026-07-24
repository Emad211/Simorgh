# ADR 0007: Verified Android `open_app` execution

- Status: Accepted
- Date: 2026-07-24

## Context

Simorgh's first real Android side effect is opening an application. A fire-and-forget implementation is unreliable because:

1. Android background Activity-launch policy varies by platform generation;
2. individually valid fields can form a semantically unsafe command;
3. the UI can change after Core observes it but before the phone executes the command;
4. a Core connection can be invalidated between a local capture and the launch call;
5. Simorgh can lose foreground visibility between an initial guard and the actual Android call;
6. Android accepting a launch API does not prove that the requested application became visible;
7. a process restart after an uncertain side effect must not repeat the launch.

The executor must work from Android 7/API 24 through current Android releases, including Samsung One UI, without treating API acceptance as success or repeating a launch when the desired state already exists.

## Decision

Simorgh will implement `open_app` as one typed, evidence-bound vertical slice.

### Mandatory target-package proof

An `open_app` command must contain at least one `active_package_equals` predicate matching `operation.package_name`. Every active-package predicate in that command must name the same target.

The rule is enforced:

- by Core before action-broker ownership;
- by Android after transport decoding.

Additional predicates are allowed. A node predicate alone can never prove that the requested application is active.

### Versioned launch eligibility

The runtime policy is explicit and JVM-testable:

- API 24–28: Simorgh does not impose an overlay prerequisite;
- API 29+: launch is eligible only when a Simorgh Activity is visible or `SYSTEM_ALERT_WINDOW` is granted and confirmed through `Settings.canDrawOverlays`.

A Foreground Service alone is not launch authorization on restricted platform versions. When the modern prerequisite is absent, the result is `blocked / unsupported_capability / attempts=0`.

Eligibility is checked once before target resolution and again immediately before `startActivity` or `startIntentSender`.

### Versioned launch adapter

- API 24–32: `PackageManager.getLaunchIntentForPackage` and an explicit new-task launch.
- API 33+: `PackageManager.getLaunchIntentSenderForPackage`, invoked through `Context.startIntentSender`.
- Explicit URI: package-scoped `ACTION_VIEW`; URI requires a non-empty scheme.

The API 33 adapter is isolated behind `@RequiresApi(33)`. `NameNotFoundException` and `SendIntentException` map to `target_not_found`.

### IntentSender background-start grants

The sender opt-in is selected by a pure policy and applied behind explicit API guards:

- API 33: legacy boolean opt-in;
- API 34–35: `MODE_BACKGROUND_ACTIVITY_START_ALLOWED`;
- API 36+ while Simorgh is visible: `MODE_BACKGROUND_ACTIVITY_START_ALLOW_IF_VISIBLE`;
- API 36+ while Simorgh is backgrounded with overlay access: `MODE_BACKGROUND_ACTIVITY_START_ALLOW_ALWAYS`.

Android 16 split the earlier single mode. Simorgh uses the narrower visible-only mode whenever possible and the always-allow mode only for the explicitly configured private background case.

### Initial evidence binding

Before fresh capture, Android requires:

- a recent observation acknowledged by Core;
- satisfaction of every declared observation precondition.

### Fresh capture and TOCTOU protection

Android requests a new local Accessibility snapshot and requires equality between its canonical projected fingerprint and the acknowledged fingerprint. A mismatch is a TOCTOU failure and blocks execution.

When an active Accessibility root exists, root package and window identity override potentially stale event hints.

### Launch-boundary revalidation

After fresh capture and immediately before launch, Android reads the current Core acknowledgement again. It must still exist, satisfy all command preconditions, and match the fresh local fingerprint.

This prevents a disconnect or Core-session replacement between capture and launch from leaving a stale local variable executable.

### Idempotency

The complete verification policy is evaluated against the fresh pre-launch snapshot. If it is already satisfied, the operation succeeds with zero attempts and no Activity launch.

Because target-package proof is mandatory, this state also proves the requested package is already active.

### Success verification

After launch acceptance, Android requires:

- one or more newer local snapshots satisfying all typed predicates;
- the configured count of stable samples with one canonical fingerprint;
- the newest locally captured state still being that satisfying state;
- a newer Core acknowledgement for that fingerprint.

The final local-state check and acknowledgement selection occur under the evidence monitor to close arrival-order races.

Only then is the result `succeeded`.

### Evidence history

The process retains bounded histories:

- 32 complete projected local snapshots;
- 64 compact acknowledgement references.

Compact acknowledgements contain stream, sequence, fingerprint, snapshot ID, capture time, active package, and acknowledgement time. They do not duplicate full UI trees.

### Reconnect evidence sessions

Acknowledged evidence is invalidated on disconnect and on detected send failure. Subscribers remain installed. Publication and invalidation callbacks are serialized.

After a new registered connection, fingerprint deduplication is reset and the latest projected state is resubmitted even when the visible UI did not change.

### Simorgh self-state

Opening Simorgh itself is supported through a minimal package-only projection, not by transmitting its internal UI:

```text
active_package = ai.simorgh.android
active_window_id = null
root_node_id = null
windows = []
nodes = []
```

The same projection is used by transport and local evidence. See ADR 0008.

### Crash safety

The encrypted write-ahead ledger from ADR 0006 is committed before handler ownership. If execution becomes uncertain after process death, Android produces a conservative blocked result and does not replay the launch.

## Consequences

### Positive

- A successful result proves the requested package and every additional postcondition.
- Semantically unsafe commands never enter the execution channel.
- Android-version differences are explicit and testable.
- Android 7–9 are not blocked by an unnecessary overlay requirement.
- Android 13–16 sender modes are selected deliberately rather than by one deprecated blanket mode.
- Modern background launch restrictions become typed and diagnosable.
- Eligibility is rechecked at the actual side-effect boundary.
- Stale plans and invalidated Core sessions cannot cross the launch boundary.
- Already-satisfied requests avoid needless task switching.
- Simorgh can prove transitions into its own Activity without exposing internal fields.
- Fast ACKs and UI transitions are not lost between polling iterations.
- The same evidence architecture can later support click, type, and scroll.

### Negative

- A launch can time out even when the target briefly appeared but no matching Core acknowledgement arrived.
- Private always-on mode on Android 10+ normally needs user-granted overlay access when Simorgh is not visible.
- OEM and lock-screen behavior still require physical validation.
- Short histories consume more memory than a latest-only design.
- Execution is intentionally slower than direct `startActivity` because it captures and verifies evidence.
- Some deep links that intentionally hand off to another package cannot satisfy the mandatory target-package predicate.
- Wall-clock skew remains a known limitation tracked in issue #23.
- Core action-journal durability remains a separate requirement tracked in issue #22.

## Rejected alternatives

### Let arbitrary predicates define `open_app` success

Rejected because an unrelated node or state could already exist in another app, producing false zero-attempt success.

### Treat the Activity-start API return as success

Rejected because launch APIs are asynchronous and platform/OEM behavior may suppress, redirect, or delay the visible transition.

### Always launch when the target is already active

Rejected because it can reset navigation state, interrupt the user, or create unnecessary task transitions.

### Use only the last snapshot received by Core

Rejected because the UI may change between observation and execution.

### Validate Core evidence only once

Rejected because the connection can be invalidated after fresh capture but before the Activity-start call.

### Check background eligibility only before target lookup

Rejected because Simorgh visibility can change before the Android side-effect call.

### Use only local post-action evidence

Rejected because the final result would not be independently visible to Core.

### Use only a Core acknowledgement without stable local samples

Rejected because a transient frame can satisfy a predicate without representing settled UI state.

### Require overlay on every supported Android version

Rejected because Simorgh supports API 24–28, before the general Android 10 background Activity-start restrictions used by the modern policy.

### Use the deprecated `ALLOWED` mode on all future Android versions

Rejected because Android 16 provides narrower visible-only and explicit always-allow modes.

### Assume a Foreground Service authorizes modern Activity starts

Rejected because Android separates long-running visible services from background Activity-launch eligibility.

### Exclude every Simorgh self-snapshot

Rejected because transitions into Simorgh would become unverifiable. A package-only projection provides sufficient evidence without exposing internal UI.

### Depend solely on package queries

Rejected on API 33+ because `getLaunchIntentSenderForPackage` provides a front-door launch token not restricted by ordinary package visibility. The older path remains necessary for API 24–32.

## Follow-up

- complete fully green CI and lint for API 24–36;
- execute the physical validation protocol on Samsung Galaxy A53;
- add a deterministic fixture application for launch and postcondition tests;
- implement explicit fresh-observation handshake in issue #21;
- implement durable Core action journal in issue #22;
- implement clock normalization in issue #23;
- record One UI background-launch, lock-screen, and battery-mode behavior;
- implement `click_node` only after live node reacquisition and its own evidence are complete.
