# Android action transport

Status: typed, capability-gated, clock-safe, restart-safe transport implemented with one live verified side effect: `open_app`.

## Purpose

This subsystem moves one validated action from trusted Simorgh Core to one private Android device and returns one typed, evidence-bound result without silently repeating an uncertain side effect.

Natural language and model output do not cross the execution boundary. Core accepts only a schema-versioned `AndroidActionCommand`; deterministic transport, clock, ledger, capability, and evidence agents decide whether it can execute.

## Specialist pipeline

```text
Planner / specialist model Agent on Core
    produces typed intent only
        ↓
Core semantic + capability Agent
    validates operation and current Session
        ↓
Core durability Agent
    journals stable action identity
        ↓
Android Transport Agent
    validates envelope and clock generation
        ↓
Android Clock Agent
    authorizes bounded deadline lease
        ↓
Android Execution Agent
    verifies fresh UI and crosses one side-effect boundary
        ↓
Android Result Agent
    persists and retries exact typed result
```

Only the first optional planning layer may use a model. Everything after typed command construction is deterministic and incurs zero model/API cost.

## Non-negotiable invariants

1. One device has at most one non-terminal action.
2. Schema availability is not execution permission.
3. Every live operation requires explicit versioned capabilities.
4. `open_app` requires both executor and bounded-clock capabilities.
5. Initial negotiation fails before command envelope and broker ownership.
6. Core persists action ownership before returning status or writing to the device.
7. Android clock admission occurs before encrypted ledger ownership for a new command.
8. `command_id`, `action_id`, command `message_id`, and result `message_id` remain distinct and stable.
9. Core restart never proves Android did not receive or execute a command.
10. Android restart never blindly repeats uncertain execution.
11. Result identity is persisted before result ACK.
12. A prior unacknowledged Android result blocks a new command.
13. Side-effect success requires fresh local state and exact Core-acknowledged evidence.
14. Model-provider credentials never cross the Core boundary.

## Credentials and persistence

```dotenv
SIMORGH_DEVICE_TOKEN=<phone-to-core-websocket-token>
SIMORGH_OPERATOR_TOKEN=<trusted-core-action-api-token>
AVALAI_API_KEY=<core-only-model-provider-key>
SIMORGH_ACTION_JOURNAL_PATH=.simorgh/action-journal.sqlite3
SIMORGH_ACTION_JOURNAL_MAX_TERMINAL_RECORDS=256
```

The Android token, operator token, and provider key are independent credentials. Action journals and ledgers do not contain bearer tokens.

## Operator API

```http
POST /v1/devices/{device_id}/actions
GET  /v1/devices/{device_id}/actions/{action_id}
POST /v1/devices/{device_id}/actions/{action_id}/cancel
Authorization: Bearer <SIMORGH_OPERATOR_TOKEN>
```

`POST /actions` accepts only `AndroidActionCommand`.

## Capability negotiation

Current mapping:

```text
open_app ->
    android.open_app.execution.v1
    android.core_clock.bounded_estimate.v1
```

The first capability proves the executor is installed. The second proves the APK applies bounded Core-time and monotonic-duration rules.

A device lacking either capability receives typed HTTP 409 `unsupported_device_capability`; Core creates no command record or envelope.

Schema operations reserved for future agents remain non-dispatchable until they have an executor, capability, evidence contract, deterministic tests, and physical validation.

Dispatch ordering:

```text
schema validation
    ↓
cross-field semantic validation
    ↓
operation → required capabilities
    ↓
current Session capability check
    ↓
identifier + single-flight checks
    ↓
command envelope
    ↓
durable queued record
    ↓
current Session revalidation
    ↓
durable delivery uncertainty
    ↓
socket write
```

Typed API failures include:

- 409 `device_not_connected`;
- 409 `unsupported_device_capability`;
- 422 `unsupported_operation`;
- 503 `action_journal_unavailable`.

## Wire messages

| Direction | Type | Correlation |
|---|---|---|
| Core → Android | `device.action_command` | stable command message ID |
| Android → Core | `device.action_command_ack` | command message ID |
| Android → Core | `device.action_result` | stable result message ID; correlation = command message ID |
| Core → Android | `device.action_result_ack` | result message ID |
| Core → Android | `device.action_cancel` | stable cancel message; correlation = command message ID |
| Android → Core | `device.action_cancel_ack` | cancel message ID |

All messages use protocol envelope `1.0` and fail closed on byte, version, UUID, device, correlation, or payload errors.

## Command admission on Android

For a new command Android performs:

```text
contract validation
    ↓
existing-ledger duplicate/busy resolution
    ↓
bounded Core clock admission
    ↓
executor availability
    ↓
encrypted active-ledger commit
    ↓
executor submission
```

Clock outcomes:

- definitely expired bounded interval → `expired` ACK;
- uncertainty overlaps deadline → `rejected` ACK;
- clock unavailable/stale/unstable → `rejected` ACK;
- issued time later than latest possible Core time → `rejected` ACK.

No new ledger entry is written for those failures.

Exact active/completed duplicates and process-death recovery are resolved from stable identity without starting a new side effect.

## Command acknowledgement statuses

- `accepted`: encrypted ledger committed and executor accepted ownership;
- `duplicate`: exact command is active or completed;
- `busy`: another action or result owns Android's slot;
- `expired`: command is definitely past its bounded deadline;
- `rejected`: contract, capability, clock certainty, ledger, or executor prevented acceptance.

An ACK proves receipt/ownership, not visible UI success.

## Bounded execution lease

`open_app` receives an action-scoped lease tied to Core clock generation and Android `elapsedRealtime`.

The lease is never extended and is checked before:

1. fresh pre-launch capture;
2. evidence revalidation;
3. the immediate `launcher.launch()` call;
4. post-launch verification.

Android uses the minimum of initial local budget, latest bounded Core budget, and requested operation timeout.

A clock-generation change before launch prevents the side effect. After accepted launch, uncertainty produces a conservative result but never command replay.

See [`ANDROID_CORE_CLOCK.md`](ANDROID_CORE_CLOCK.md).

## Evidence and success

Before launch:

- the latest Core-acknowledged observation must satisfy typed preconditions;
- observation age is measured from local monotonic capture time;
- Android explicitly captures current local state;
- current local fingerprint must match current Core-acknowledged fingerprint;
- the lease must remain safe immediately before launch.

After launch:

- declared predicates must be satisfied;
- stable local samples must exist;
- exact matching observation must be acknowledged by Core;
- after sequence/Core receive order must prove newer evidence;
- capture must occur strictly before the conservative lease deadline.

Android wall-clock metadata remains exact audit identity but does not determine freshness or before/after order.

For non-URI `open_app`, Android may return zero-attempt success only when a fresh state already satisfies the destination and matches current Core evidence. Explicit URI operations always require an accepted launch attempt.

## Result timestamps

```text
started_at_ms = bounded Core midpoint at lease start
finished_at_ms = started_at_ms + monotonic elapsed duration
```

Wall-clock changes and later estimate jumps cannot alter duration. Exception handling after an accepted launch uses the stored lease.

## Durable Core action broker

Core stores a versioned SQLite journal and validated memory mirror.

```text
queued → delivered → accepted → completed
                     └────────→ cancelled
queued/delivered/accepted → cancelling → completed/cancelled
non-terminal → rejected/expired where allowed
```

The broker enforces write-before-visible transitions, immutable identity, monotonic counters/timestamps, exact result replay, current Session capability, bounded terminal history, and fail-closed HTTP 503 behavior.

See [`CORE_ACTION_JOURNAL.md`](CORE_ACTION_JOURNAL.md).

## Android encrypted write-ahead ledger

Before executor invocation Android persists:

```text
schema_version
command_envelope_id
command_hash
command
phase = active
```

The ledger uses AES-GCM with a non-exportable Android Keystore key and synchronous commit.

After completion Android atomically stores:

```text
phase = completed
result_message_id
result
result_acknowledged = false
```

Reconnect reuses exact result identity.

## Restart boundaries

### Android process death during uncertain execution

Android does not replay. It publishes a conservative blocked/internal-error recovery result.

### Core restart after uncertain command delivery

Core does not redispatch a command that may have crossed the device boundary. It waits for Android's stable result or original deadline.

### Core crash after result persistence but before ACK

Android replays the exact result; Core loads durable identity and sends `duplicate`; Android clears its ledger.

Changed result identity or content is a conflict.

## Cancellation

Cancellation is cooperative, not rollback:

1. Core persists one stable cancel envelope;
2. Android verifies action identity against its ledger;
3. the active executor receives `cancel()`;
4. Android returns `accepted`, `duplicate`, `not_found`, or `completed`;
5. the executor still owns the final result.

Cancellation can be redelivered because it attempts to stop work rather than repeat the original side effect.

## Cost profile

The deterministic action path performs:

- zero model calls after typed command construction;
- no extra clock network calls;
- no repeated planning call on retry;
- bounded SQLite/ledger writes;
- bounded probe, queue, and evidence history;
- exact-envelope retry rather than regeneration;
- UI capture only at explicit evidence boundaries.

Specialist planning agents should cache and reuse validated typed plans where identity permits, but must never cache execution authorization, clock leases, fresh evidence, or side-effect results as if they were current.

## Failure matrix

| Failure | Behavior |
|---|---|
| device disconnected | Core 409; no action record |
| executor capability missing | Core 409; no action record |
| bounded-clock capability missing | Core 409; no action record |
| unsupported operation | Core 422; no action record |
| Core journal failure | Core 503; no unsafe memory-only mutation |
| Android clock unavailable/uncertain | command rejected before ledger |
| command definitely expired | command ACK expired |
| clock generation changes before launch | no side effect |
| socket write uncertain after durable delivery | no blind resend after restart |
| duplicate active command | no second executor submission |
| Android process dies active | blocked recovery result; no replay |
| Core dies after result persistence | exact replay receives duplicate ACK |
| result identity/content changes | conflict; state not overwritten |
| success evidence captured at/after deadline | timed out, not succeeded |
| journal/schema corruption | Core startup fails closed |

## Automated validation

Core and Android tests cover:

- capability negotiation for executor and bounded clock separately;
- absence of command leakage on negotiation failure;
- positive/negative device skew and high RTT;
- registration/heartbeat correlation and sequence;
- stale probes and reconnect generations;
- cross-client generation isolation;
- definite expiry versus uncertainty overlap;
- lease non-extension;
- wall-clock jump during execution;
- monotonic observation freshness and ordering;
- zero wire bytes/fingerprint changes from local monotonic timestamp;
- launch-boundary generation change;
- successful evidence capture deadline;
- exceptional result timestamps using the original lease;
- encrypted ledger duplicate/process-death behavior;
- Core durable restart and exact result replay;
- cancellation and result correlation.

## Physical Galaxy A53 boundary

Automated CI does not claim One UI validation. Physical testing must record Android/One UI/security versions, APK/Core commits, capabilities, RTT/uncertainty, wall-clock changes, reconnects, foreground/background launch conditions, evidence timing, command/result identity, and proof that an uncertain command never executes twice.

## Current boundary

Live actions:

```text
open_app(package_name)
open_app(package_name, uri)
```

All other operations remain disabled until their specialist executor increments are independently reviewed and validated.