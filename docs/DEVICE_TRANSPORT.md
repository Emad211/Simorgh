# Android device transport

Status: authenticated registration, bounded Core-clock synchronization, liveness, read-only observation, refresh, and crash-safe typed action transport implemented.

## Endpoint and credentials

Android connects through:

```text
GET /v1/devices/ws
Authorization: Bearer <SIMORGH_DEVICE_TOKEN>
```

Credential boundaries:

- `SIMORGH_DEVICE_TOKEN` authenticates only the Android WebSocket;
- `SIMORGH_OPERATOR_TOKEN` authorizes trusted Core action/refresh APIs;
- AvalAI and other model-provider keys remain only on Core;
- clock probes, Accessibility observations, and typed actions never contain provider credentials.

## Connection lifecycle

```text
Android foreground service           Simorgh Core
    |--- WebSocket ------------------------->|
    |--- device.register ------------------->|  monotonic send probe
    |<-- device.registered ------------------|  correlated server_time_ms
    |--- device.heartbeat ------------------>|  bounded monotonic probe
    |<-- device.heartbeat_ack ---------------|  correlation + sequence
    |--- device.observation ---------------->|
    |<-- device.observation_ack -------------|
    |<-- device.observation_refresh ---------|
    |--- device.observation_refresh_ack ---->|
    |--- correlated device.observation ----->|
    |<-- device.action_command --------------|
    |--- device.action_command_ack --------->|
    |--- device.action_result -------------->|
    |<-- device.action_result_ack -----------|
    |<-- device.action_cancel ---------------|
    |--- device.action_cancel_ack ---------->|
```

The first application message must be `device.register`. Core rejects an invalid token, device ID, protocol envelope, registration payload, or unsupported message.

The WebSocket is owned by `SimorghConnectionService`, not the Activity. Closing the UI does not intentionally close the device session.

## Protocol envelope

Every message contains:

- `protocol_version`;
- UUID `message_id`;
- typed `type`;
- non-negative `sent_at_ms`;
- `device_id`;
- optional `correlation_id`;
- structured payload.

Current protocol version: `1.0`.

Inbound messages fail closed when byte size, protocol version, UUID identity, device identity, correlation, sequence, timestamp shape, or typed payload is invalid.

## Registration and bounded Core clock

`device.registered` is both registration confirmation and the first bounded Core-clock sample.

Android records `elapsedRealtime` immediately before sending `device.register`. The response must:

- correlate to the exact registration message ID;
- carry valid `server_time_ms`;
- belong to the active physical socket generation;
- yield a stable Core-time interval.

The connection becomes `CONNECTED` only after this clock sample is valid. Merely decoding `device.registered` is not enough.

Every existing heartbeat refines the same interval; no extra clock request or polling loop is introduced.

See [`ANDROID_CORE_CLOCK.md`](ANDROID_CORE_CLOCK.md).

## Generation model

Two independent generation guards are used:

```text
logical connection generation
    user connect/disconnect lifecycle

physical socket/clock generation
    every WebSocket attempt and reconnect
```

Additionally, the shared clock estimator uses a process-wide unique generation so an obsolete client instance cannot invalidate a newer instance that reused the same local counter.

Callbacks, probes, and ACKs from obsolete generations cannot mutate current transport or clock state.

## Heartbeat probe semantics

Each heartbeat probe retains only:

```text
message_id
sequence
sent_at_elapsedRealtime
socket_generation
```

The response must match correlation ID and sequence.

- exact ACK: update clock estimate;
- unknown/evicted late ACK: ignore without closing a healthy connection;
- identity or sequence mismatch: protocol failure;
- probe set: bounded to 32 by default.

This adds O(1) local arithmetic and no network traffic beyond the heartbeat already required for liveness.

## Resilience

Android transport implements:

- registration before normal traffic;
- bounded Core-clock registration before side-effect availability;
- WebSocket-level pings;
- application heartbeat negotiated by Core;
- bounded exponential reconnect delay from 1 to 30 seconds;
- generic outbound queue bounded to 100 messages;
- obsolete-socket callback suppression;
- replacement of an older live Session for the same device;
- sticky foreground-service recovery;
- optional restoration after boot;
- ordered latest-wins Accessibility observations;
- explicit observation refresh and correlation;
- encrypted Android action write-ahead state;
- stable result delivery after reconnect;
- exact command-envelope replay where safe;
- separate command/result/cancellation identity.

Observation and action-result messages bypass the generic queue. Their dedicated publishers own coalescing, ordering, stable message identity, and ACK retry so generic queue eviction cannot corrupt them.

## Cost profile

The device transport's deterministic runtime path performs:

- zero LLM/model calls;
- zero AvalAI calls;
- zero extra clock requests;
- no periodic UI screenshot upload;
- no installed-app inventory upload;
- bounded queues and probe maps;
- integer interval calculations only.

Planning agents may use models on Core, but model output never controls transport identity, time math, replay, ledger mutation, or side-effect verification.

## Current side-effect surface

Live typed operation:

```text
open_app(package_name)
open_app(package_name, uri)
```

Core dispatch requires current Session capabilities:

```text
android.open_app.execution.v1
android.core_clock.bounded_estimate.v1
```

All other action schema variants remain non-dispatchable until an independent executor, capability, evidence contract, tests, and physical validation are merged.

See:

- [`OBSERVATION_TRANSPORT.md`](OBSERVATION_TRANSPORT.md);
- [`OBSERVATION_REFRESH.md`](OBSERVATION_REFRESH.md);
- [`ANDROID_ACTION_TRANSPORT.md`](ANDROID_ACTION_TRANSPORT.md).

## Local development

Create `.env`:

```dotenv
SIMORGH_DEVICE_TOKEN=<long-random-device-token>
SIMORGH_OPERATOR_TOKEN=<different-long-random-operator-token>
SIMORGH_HOST=0.0.0.0
SIMORGH_PORT=8080
```

Run Core:

```bash
uvicorn simorgh_core.app:app --host 0.0.0.0 --port 8080 --reload
```

Android emulator endpoint:

```text
ws://10.0.2.2:8080/v1/devices/ws
```

Physical phone on a trusted LAN:

```text
ws://<computer-lan-address>:8080/v1/devices/ws
```

The debug manifest permits local cleartext `ws://`. Production disables cleartext and requires `wss://`.

## Secret storage

The device token is encrypted with AES-GCM using a non-exportable Android Keystore key. Preferences store ciphertext, IV, endpoint, and service preferences only.

The Android action ledger uses a separate Keystore-backed AES-GCM key. The operator token and model-provider credentials are never stored on Android.

The shared development token is a foundation, not final pairing. Per-device revocable credentials remain a separate increment.

## Foreground-service behavior

The connection service is user-visible, has an ongoing notification and Stop action, and owns:

- WebSocket transport;
- bounded clock synchronization;
- observation publisher;
- refresh coordinator;
- action router;
- encrypted ledger;
- result publisher;
- current `open_app` executor.

No network, planning, model inference, or tool selection runs inside Accessibility callbacks.

See [`ANDROID_ALWAYS_ON.md`](ANDROID_ALWAYS_ON.md) for Android-version and Samsung configuration details.

## Physical validation boundary

Automated tests validate protocol, correlation, reconnect, clock bounds, queue limits, action replay, and APK build. They do not substitute for Samsung Galaxy A53 / One UI validation.

Record exact Android/One UI versions, APK/Core commits, network topology, registration RTT, heartbeat uncertainty, reconnect behavior, wall-clock changes, command/result identities, and proof that no uncertain command executes twice.