# ADR 0007: Verified Android `open_app` execution

- Status: Accepted
- Date: 2026-07-24

## Context

Opening an Android application appears simple, but a fire-and-forget implementation is not reliable enough for an always-on personal agent:

1. Android background Activity-launch policy changes across platform generations.
2. Android 11+ filters package-query visibility.
3. Individually valid command fields can form an unsafe cross-field goal.
4. The UI can change after Core observes it but before Android executes.
5. Core evidence can be invalidated after fresh capture but before launch.
6. Simorgh can lose foreground visibility immediately before the platform call.
7. A URI can target a destination inside an already-active app; package presence alone is insufficient proof.
8. Android accepting a launch call does not prove the requested state became visible.
9. A newer observation can reach Core before the valid result referencing an earlier acknowledged state.
10. Canonical UI fingerprints deliberately ignore capture identity, so they cannot alone prove exact message replay.
11. Process death after an uncertain side effect must not repeat the launch.

The first live side effect must work from Android 7/API 24 through current Android releases, including Samsung One UI, while failing closed at every uncertain boundary.

## Decision

Simorgh will implement `open_app` as one typed, evidence-bound vertical slice.

### 1. Mandatory package proof

Every `open_app` verification policy contains at least one `active_package_equals` predicate matching `operation.package_name`. All active-package predicates must name the same target.

Core enforces this before broker ownership. Android enforces it again after transport decoding.

### 2. Deep-link destination proof

If `operation.uri` is present:

- at least one node predicate targeting `operation.package_name` is required;
- all node predicates in the policy must target the operation package;
- zero-attempt success is forbidden;
- Android always performs one URI launch attempt and verifies fresh post-action state;
- Core rejects a successful URI result reporting zero attempts.

A package predicate alone cannot prove URI navigation.

### 3. Narrow package visibility

Simorgh does not request `QUERY_ALL_PACKAGES` for this operation.

For API 24–32, the manifest declares the exact front-door signatures used by `getLaunchIntentForPackage`:

- `ACTION_MAIN/CATEGORY_INFO`;
- `ACTION_MAIN/CATEGORY_LAUNCHER`.

For API 33+, `getLaunchIntentSenderForPackage` is used and is not restricted by ordinary package visibility. Explicit URI launches are attempted directly and map `ActivityNotFoundException` to `target_not_found`.

### 4. Versioned launch eligibility

The runtime policy is pure and JVM-tested:

- API 24–28: Simorgh imposes no overlay prerequisite;
- API 29+: Simorgh must be visible or `SYSTEM_ALERT_WINDOW` must be granted and confirmed through `Settings.canDrawOverlays`.

A Foreground Service alone is not modern Activity-start authorization. Missing eligibility yields `blocked / unsupported_capability / attempts=0`.

Eligibility is checked before resolution and again immediately before the side effect.

### 5. Versioned launch adapter

- API 24–32: `PackageManager.getLaunchIntentForPackage` and explicit new-task launch.
- API 33+: `PackageManager.getLaunchIntentSenderForPackage` through `Context.startIntentSender`.
- Explicit URI: package-scoped `ACTION_VIEW` with a non-empty scheme.

The API 33 path is isolated by SDK guards. `NameNotFoundException` and `SendIntentException` map to `target_not_found`.

### 6. Versioned IntentSender mode

- API 33: legacy boolean sender opt-in;
- API 34–35: `MODE_BACKGROUND_ACTIVITY_START_ALLOWED`;
- API 36+ while Simorgh is visible: `ALLOW_IF_VISIBLE`;
- API 36+ while backgrounded with overlay access: `ALLOW_ALWAYS`.

The narrower Android 16 visible-only mode is used whenever possible.

### 7. Initial evidence binding

Before fresh capture, Android requires a recent Core-acknowledged observation satisfying every command precondition:

- stream ID;
- minimum sequence;
- state fingerprint;
- active package;
- maximum age.

### 8. Fresh capture and TOCTOU protection

Android requests a new local Accessibility snapshot and requires its projected canonical fingerprint to equal the acknowledged fingerprint.

The active Accessibility root, when present, is authoritative for package and window identity; event hints are fallback values.

A mismatch blocks execution before launch.

### 9. Launch-boundary Core-evidence revalidation

Immediately before idempotency evaluation or launch, Android reads the current Core acknowledgement again. It must still exist, satisfy all preconditions, and match the fresh local state.

This closes the disconnect/session-replacement race between capture and side effect.

### 10. Front-door idempotency

For `uri=null`, Android evaluates all postconditions against fresh state. If already satisfied, the operation succeeds with zero attempts and no Activity launch.

Target-package proof makes zero-attempt success equivalent to “the requested app is already active in the declared state.”

### 11. URI non-idempotent navigation boundary

For an explicit URI, pre-existing visible predicates do not suppress launch. URI navigation always owns one side-effect attempt because the user requested navigation, not merely package activation.

Fresh destination evidence is still required after the platform call.

### 12. Android success verification

After launch acceptance, Android requires:

- newer local snapshots satisfying all typed predicates;
- the configured stable-sample count with one fingerprint;
- the newest local state still satisfying the policy;
- a newer Core acknowledgement for the successful fingerprint.

The final local check and acknowledgement selection occur under one monitor to close arrival-order races.

### 13. Android bounded evidence history

The process keeps:

- 32 complete projected local snapshots;
- 64 compact acknowledgement references.

Compact acknowledgements do not duplicate full UI trees.

### 14. Core result verification

Android result payloads are untrusted claims until Core validates them against the original command and Core's own acknowledged evidence.

Successful results require:

- matching command/action identity;
- exact before and after references in Core history;
- target-package proof;
- Predicate Evidence length and order matching the policy;
- every outcome `satisfied`;
- no selector resolution for `active_package_equals`;
- `resolved` outcome plus selected node ID/path for positive node predicates;
- `not_found` and no selected node for successful `node_absent`;
- identical before/after for zero-attempt front-door success;
- newer after evidence for one-attempt success;
- non-reversed Core acknowledgement order;
- exact command-envelope correlation;
- one accepted attempt for URI success.

Invalid proof receives `device.action_result_ack(status=rejected)` and is not stored as terminal success.

### 15. Core bounded acknowledged history

Core retains 256 compact acknowledged observations per device, keyed by stream, sequence, snapshot ID, and fingerprint.

This permits a valid result to reference an earlier acknowledged state even if a newer observation arrived first. With a normal 500 ms observation interval and 120-second maximum command lifetime, at most 240 normally rate-limited observations fit in one command lifetime; 256 provides bounded margin.

Evicted evidence fails closed.

### 16. Exact replay integrity

Because canonical state fingerprints ignore capture identity and time, Core also stores SHA-256 over the complete normalized observation payload for each recent `message_id`.

An exact replay refreshes both message and evidence LRU entries. Reusing a message ID with altered capture time, snapshot metadata, or any other payload field is rejected as a conflict.

### 17. Reconnect evidence sessions

Android invalidates executable acknowledged evidence on disconnect and detected send failure while preserving subscribers. After new registration it clears state deduplication and resubmits the latest projected state.

An acknowledgement from a previous Core connection cannot cross the launch boundary.

### 18. Simorgh self-state

Transitions into Simorgh are proved with a minimal package-only projection:

```text
active_package = ai.simorgh.android
active_window_id = null
root_node_id = null
windows = []
nodes = []
```

The same projection is used by transport and local evidence. See ADR 0008.

### 19. Crash safety

The encrypted Android write-ahead ledger is committed before handler ownership. If process death leaves execution uncertain, Android emits a conservative blocked result and does not replay the launch.

## Consequences

### Positive

- Successful results prove both package activation and declared destination state.
- Core independently verifies Android success claims.
- URI navigation cannot be skipped because the app is already foregrounded.
- A valid result survives a newer observation arriving first.
- Exact observation replay cannot alter ignored fingerprint metadata.
- Semantically unsafe commands never enter the side-effect handler.
- Package visibility is limited to launchable front-door signatures.
- Android-version differences and IntentSender modes are explicit and testable.
- Android 7–9 are not blocked by an unnecessary overlay prerequisite.
- Modern background restrictions are typed and diagnosable.
- Stale plans and invalidated Core sessions cannot cross the launch boundary.
- Fast ACKs and transitions are retained by bounded histories.
- Simorgh can prove self-transitions without exposing internal fields.
- The evidence model can be reused by click, type, and scroll.

### Negative

- Execution is slower than direct `startActivity` because it captures and verifies evidence.
- A visibly successful launch can still time out when no matching Core acknowledgement arrives.
- Private background launch on Android 10+ normally needs user-granted overlay access.
- A URI requires a stable destination node predicate; some applications may not expose one reliably.
- Bounded histories consume memory and can evict valid but excessively delayed evidence.
- A rejected result intentionally blocks later Android actions until repaired.
- OEM, lock-screen, and battery behavior still require physical validation.
- Wall-clock skew remains issue #23.
- Durable Core restart recovery remains issue #22.

## Rejected alternatives

### Request `QUERY_ALL_PACKAGES`

Rejected because `open_app` needs launchable front doors, not the complete installed-app inventory. Targeted `<queries>` and the API 33 IntentSender path provide a smaller information surface.

### Let arbitrary predicates prove package launch

Rejected because an unrelated node could already exist in another app and create false zero-attempt success.

### Let package presence prove URI navigation

Rejected because an app can be active on the wrong destination.

### Skip URI launch when destination predicates already appear true

Rejected because explicit URI is a navigation instruction and pre-action state may be stale, coincidental, or semantically different despite similar nodes.

### Treat Android API return as success

Rejected because Activity-start calls are asynchronous and OEM/platform behavior may suppress or redirect the visible transition.

### Validate a result only against Core's latest observation

Rejected because result and observation message ordering is asynchronous. Exact bounded ACK history distinguishes benign ordering from fabricated evidence.

### Use canonical state fingerprint as exact replay proof

Rejected because capture identity and time are intentionally excluded from state deduplication.

### Validate Core evidence only once on Android

Rejected because the connection can be invalidated after capture but before launch.

### Check background eligibility only before lookup

Rejected because visibility can change before the platform call.

### Use only local post-action evidence

Rejected because Core could not independently verify the result.

### Use only Core acknowledgement without stable local samples

Rejected because one transient frame is not settled UI state.

### Require overlay on every Android version

Rejected because API 24–28 predate the modern restriction used by this compatibility policy.

### Use the deprecated broad mode on all future Android versions

Rejected because Android 16 provides narrower visible-only and explicit always-allow modes.

### Exclude all Simorgh self-snapshots

Rejected because transitions into Simorgh would become unverifiable.

## Follow-up

- complete fully green CI for the final PR head;
- execute and record the Samsung Galaxy A53 validation protocol;
- add a deterministic fixture app with stable front-door and URI destinations;
- implement the fresh-observation handshake in #21;
- implement durable Core action journal in #22;
- implement clock normalization in #23;
- record One UI background-launch, lock-screen, and battery behavior;
- implement `click_node` only after live-node reacquisition and separate proof are complete.
