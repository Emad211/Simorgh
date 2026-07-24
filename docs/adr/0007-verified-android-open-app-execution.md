# ADR 0007: Verified Android `open_app` execution

- Status: Accepted
- Date: 2026-07-24

## Context

Simorgh's first real Android side effect is opening an application. Although this appears simple, three independent uncertainties make a fire-and-forget implementation unreliable:

1. Android restricts Activity launches from background processes.
2. the UI can change after Core observes it but before the phone executes the command;
3. Android accepting a launch API does not prove that the requested application became visible.

The executor must work from Android 7/API 24 through current Android releases, including Samsung One UI, without treating platform acceptance as success or repeating a launch when the desired state already exists.

## Decision

Simorgh will implement `open_app` as a single typed, evidence-bound vertical slice.

### Runtime launch eligibility

A launch request is issued only when:

- a Simorgh Activity is visible; or
- the user granted `SYSTEM_ALERT_WINDOW`, checked through `Settings.canDrawOverlays`.

A Foreground Service alone is not considered launch authorization. When neither condition holds, the result is blocked with `unsupported_capability`.

### Versioned launch adapter

- API 24–32: `PackageManager.getLaunchIntentForPackage` and an explicit new-task launch.
- API 33+: `PackageManager.getLaunchIntentSenderForPackage`, launched through `Context.startIntentSender` with sender-side background-launch opt-in options.
- Explicit URI: package-scoped `ACTION_VIEW`; URI requires a scheme.

### Evidence binding

Before launch, Android requires:

- a recent observation acknowledged by Core;
- satisfaction of every declared observation precondition;
- a newly captured local snapshot;
- equality between the fresh snapshot's canonical fingerprint and the acknowledged fingerprint.

A mismatch is a TOCTOU failure and blocks execution.

### Idempotency

The complete verification policy is evaluated against the fresh pre-launch snapshot. If already satisfied, the operation succeeds with zero attempts and no Activity launch.

### Success verification

After launch acceptance, Android requires:

- one or more newer local snapshots satisfying all typed predicates;
- the configured count of stable samples with one canonical fingerprint;
- a newer Core acknowledgement for that fingerprint.

Only then is the result `succeeded`.

### Evidence history

The process retains bounded histories of local snapshots and Core acknowledgements so a fast transition or acknowledgement cannot be missed between polling iterations. Histories contain immutable already-redacted Accessibility data and are process-local.

### Self-launch

`open_app` cannot target Simorgh itself because Simorgh currently filters its own package from the observation pipeline. Internal navigation requires a separate explicit contract.

## Consequences

### Positive

- A successful result has independently observed evidence.
- Background launch restrictions become typed and diagnosable.
- Android version differences are isolated inside one adapter.
- Stale plans cannot launch from a changed screen.
- Already-satisfied requests avoid needless task switching.
- The implementation remains compatible with the crash-safe action ledger from ADR 0006.
- The same observation and verification architecture can later support click, type, and scroll.

### Negative

- A launch can time out even when the target briefly appeared but no matching Core acknowledgement arrived.
- The private always-on mode requires a user-granted special access for reliable background launches.
- OEM behavior still requires physical-device validation.
- Keeping short process-local histories consumes more memory than retaining only the latest observation.
- The executor is intentionally slower than a direct `startActivity` call because it captures and verifies evidence.

## Rejected alternatives

### Treat `startActivity` return as success

Rejected because Activity launch APIs are asynchronous and platform/OEM restrictions may suppress or redirect the visible transition.

### Always launch, even when the target is already active

Rejected because it can reset navigation state, interrupt the user, or create unnecessary task transitions.

### Use only the last snapshot received by Core

Rejected because the UI may change between observation and execution. A fresh local capture and fingerprint equality are required.

### Use only local post-action evidence

Rejected because the final result would not be independently visible to Core and could be lost during transport races.

### Use only Core acknowledgement without stable local samples

Rejected because one transient frame can satisfy a predicate briefly without representing the settled UI state.

### Assume a Foreground Service can launch Activities

Rejected because Android explicitly separates long-running visible services from background Activity launch eligibility.

### Depend solely on package queries

Rejected on API 33+ because `getLaunchIntentSenderForPackage` provides a front-door launch token not restricted by package visibility. The older API path remains necessary for API 24–32.

## Follow-up

- complete CI and Android lint for API 24–36;
- execute the physical validation protocol on the Samsung Galaxy A53;
- add a deterministic fixture application for launch and postcondition tests;
- record OEM-specific behavior for One UI background launch and battery modes;
- implement `click_node` only after live node reacquisition and its own verification evidence are complete.
