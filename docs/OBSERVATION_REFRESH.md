# Observation refresh handshake

Status: implemented vertical slice for obtaining fresh Core-acknowledged Android UI evidence without weakening stale-state protection.

## Purpose

Normal Android observations are state-deduplicated. If the screen remains unchanged, Simorgh does not continuously upload the same Accessibility tree. That saves bandwidth, memory, battery, and model context.

Action preconditions are intentionally strict, however. An unchanged but old observation must not authorize a new side effect.

The refresh handshake solves this conflict:

```text
unchanged screen
    +
strict maximum_age_ms
    +
normal state deduplication
    =
explicit fresh capture on demand
```

It does not execute an Android side effect. It only captures, transports, acknowledges, and returns fresh evidence that a later typed action can bind to.

## Required device capability

The connected Android registration must advertise:

```text
android.observation.refresh.v1
```

Core rejects creation when:

- the device is disconnected;
- the current Session does not advertise the capability;
- another non-terminal refresh already owns the device.

## API authentication

Refresh endpoints use the trusted operator credential, not the device token and not an AvalAI provider key:

```http
Authorization: Bearer ${SIMORGH_OPERATOR_TOKEN}
```

`SIMORGH_DEVICE_TOKEN` remains limited to the device WebSocket.

## Create a refresh

```http
POST /v1/devices/{device_id}/observation-refreshes
Content-Type: application/json
Authorization: Bearer ${SIMORGH_OPERATOR_TOKEN}
```

Example body:

```json
{
  "timeout_ms": 5000,
  "expected_state_fingerprint": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "expected_active_package": "com.example.app",
  "reason": "refresh before opening the selected item"
}
```

Fields:

| Field | Required | Meaning |
|---|---:|---|
| `timeout_ms` | no | Android relative capture timeout, `250..10000` ms |
| `expected_state_fingerprint` | no | require the current canonical UI state to remain unchanged |
| `expected_active_package` | no | require the same active package |
| `reason` | no | bounded operator diagnostic text, not an Android instruction |

The API returns `202 Accepted` and a stable request ID.

Example:

```json
{
  "device_id": "11111111-1111-1111-1111-111111111111",
  "request_id": "22222222-2222-2222-2222-222222222222",
  "request_message_id": "22222222-2222-2222-2222-222222222222",
  "phase": "delivered",
  "created_at_ms": 1784920000000,
  "updated_at_ms": 1784920000000,
  "deadline_at_ms": 1784920005000,
  "delivery_count": 1,
  "last_session_id": "33333333-3333-3333-3333-333333333333",
  "acknowledgement": null,
  "evidence": null,
  "detail": "refresh request delivered to Android"
}
```

## Poll status

```http
GET /v1/devices/{device_id}/observation-refreshes/{request_id}
Authorization: Bearer ${SIMORGH_OPERATOR_TOKEN}
```

Phases:

| Phase | Terminal | Meaning |
|---|---:|---|
| `queued` | no | retained for reconnect delivery |
| `delivered` | no | exact request envelope was sent to current Session |
| `accepted` | no | Android owns capture or exact delivery |
| `completed` | yes | correlated observation was registered and ACKed |
| `rejected` | yes | capability, state, observer, or protocol requirement failed |
| `expired` | yes | Core or Android timeout elapsed |
| `cancelled` | yes | trusted operator cancelled the request |

Do not treat `accepted` as fresh evidence. Only `completed` contains evidence suitable for an action precondition.

## Completed evidence

Example:

```json
{
  "phase": "completed",
  "evidence": {
    "message_id": "44444444-4444-4444-4444-444444444444",
    "session_id": "33333333-3333-3333-3333-333333333333",
    "acknowledged_at_ms": 1784920000200,
    "stream_id": "55555555-5555-5555-5555-555555555555",
    "sequence": 42,
    "snapshot_id": "66666666-6666-6666-6666-666666666666",
    "state_fingerprint": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "captured_at_ms": 1784920000100,
    "active_package": "com.example.app"
  }
}
```

The evidence is an exact compact reference to an observation Core accepted or marked unchanged. It is not supplied by the model and is not reconstructed from natural language.

## Bind evidence to an Android action

Construct a new action command after refresh completion:

```json
{
  "schema_version": "1.0",
  "command_id": "77777777-7777-7777-7777-777777777777",
  "action_id": "88888888-8888-8888-8888-888888888888",
  "issued_at_ms": 1784920000250,
  "deadline_at_ms": 1784920030250,
  "precondition": {
    "expected_stream_id": "55555555-5555-5555-5555-555555555555",
    "minimum_sequence": 42,
    "expected_state_fingerprint": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "expected_active_package": "com.example.app",
    "maximum_age_ms": 2000
  },
  "operation": {
    "kind": "open_app",
    "package_name": "com.example.target"
  },
  "verification": {
    "predicates": [
      {
        "kind": "active_package_equals",
        "package_name": "com.example.target"
      }
    ],
    "timeout_ms": 10000,
    "stable_samples": 1
  }
}
```

Important:

- create a new command after receiving the evidence;
- do not reuse an expired command's issue/deadline times;
- do not enlarge `maximum_age_ms` merely to avoid refresh;
- preserve the refresh evidence fields exactly;
- the Android executor still performs its own fresh local capture and TOCTOU comparison before any side effect.

The refresh handshake is planning evidence. It does not replace Android's execution-boundary verification.

## Cancel a refresh

```http
POST /v1/devices/{device_id}/observation-refreshes/{request_id}/cancel
Content-Type: application/json
Authorization: Bearer ${SIMORGH_OPERATOR_TOKEN}
```

```json
{
  "reason": "operator changed the plan"
}
```

Cancellation is Core-side and terminal. A late Android ACK or correlated observation cannot reopen the request.

The late observation still remains valid ordinary device state and receives its normal observation ACK.

## Android protocol

### Request

```text
type           = device.observation_refresh
message_id     = request_id
correlation_id = null
```

### Immediate or terminal Android ACK

```text
type           = device.observation_refresh_ack
correlation_id = request_id
payload.request_id = request_id
```

Statuses:

```text
accepted
duplicate
busy
expired
observer_unavailable
rejected
```

### Correlated observation

```text
type           = device.observation
correlation_id = request_id
```

The observation payload is identical to ordinary observation transport. Request identity is not included in the canonical UI fingerprint.

## Publisher ordering

The Android publisher uses:

```text
one normal latest-wins pending slot
one priority refresh pending slot
one in-flight envelope
```

Rules:

1. an existing in-flight normal observation finishes first;
2. the fresh captured refresh supersedes older unsent normal state;
3. refresh is materialized next;
4. sequence is allocated only at materialization;
5. retry reuses the exact envelope;
6. after refresh ACK, future normal states resume.

This prevents sequence inversion such as sending sequence 11 before a previously queued sequence 10.

## Reconnect behavior

Core request:

- retains one exact request envelope;
- assigns delivery ownership to the latest compatible Session;
- ignores redelivery attempts from obsolete Sessions;
- preserves newer replacement ownership when an older Create path fails;
- queues after ordinary socket-send failure.

Android correlated observation:

- retains one exact in-flight envelope;
- resumes it after reconnect;
- reports the same refresh correlation;
- does not consume another observation sequence on retry.

If only the observation ACK was lost, Core classifies exact replay as duplicate and sends another ACK. Completion remains deterministic.

## Timeout model

Two clocks exist intentionally:

- Core absolute record deadline controls resource lifecycle and redelivery;
- Android relative monotonic timeout controls local capture waiting.

They may expire in either order. Once Core reaches a terminal phase, a later correctly correlated Android terminal ACK is ignored without changing final state.

This is not the same problem as cross-device action deadline normalization, which remains tracked separately in issue #23.

## Failure matrix

| Condition | Result |
|---|---|
| Device disconnected | create returns conflict |
| Capability missing | create returns conflict |
| Another refresh active | create returns conflict |
| Accessibility unavailable | Android ACK `observer_unavailable`; refresh rejected |
| No new snapshot before timeout | Android ACK `expired`; refresh expired |
| Expected package changed | observation recorded; refresh rejected |
| Expected fingerprint changed | observation recorded; refresh rejected |
| Correlated observation stale | observation ACKed as stale; refresh rejected |
| Core cannot find exact evidence | refresh rejected |
| Operator cancellation | refresh cancelled |
| Old Session sends ACK | protocol conflict; current state unchanged |
| Old Session redelivery call | ignored |
| Core expires before Android timeout ACK | Core expiry remains authoritative |
| Core restart | non-terminal refresh lost; create a new refresh |

## Privacy properties

Refresh uses the same snapshot construction and projection as ordinary observation transport:

- password-node semantic text remains redacted;
- node, depth, child, action, and text bounds remain enforced;
- Simorgh's own screen remains package-only projection;
- refresh correlation does not alter UI state or leak into model-visible text;
- no installed-app inventory is added.

## Validation

Automated tests cover:

- Python and Kotlin protocol identity;
- capability requirement;
- API create/read/cancel;
- unchanged-state forced delivery;
- exact retry identity;
- refresh priority;
- send-boundary sequence allocation;
- duplicate versus busy;
- observer unavailable and disconnect;
- timeout;
- expected-state mismatch while retaining ordinary observation;
- cancellation followed by late messages;
- exact reconnect redelivery;
- replacement Session ownership;
- failed initial delivery cleanup;
- Core expiry followed by late Android ACK;
- completed evidence used in a strict action command.

## Physical Samsung Galaxy A53 validation

Physical validation is still required before claiming One UI support for this path. Record:

1. model number;
2. Android version;
3. One UI version;
4. security patch;
5. APK commit SHA;
6. Accessibility state;
7. Core endpoint and network topology without secrets;
8. baseline observation identity;
9. refresh request ID;
10. Android ACK status and latency;
11. correlated observation identity;
12. Core completion evidence;
13. unchanged-screen case;
14. changed-screen rejection case;
15. observer-disabled case;
16. disconnect and reconnect during capture;
17. foreground and background service conditions;
18. battery-optimized and unrestricted battery modes.

See ADR 0009 for the architecture decision and failure semantics.
