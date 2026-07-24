# Android device transport

Status: registration, liveness, read-only observation, and crash-safe action transport implemented

The Android application connects to Simorgh Core through an authenticated, versioned WebSocket endpoint:

```text
GET /v1/devices/ws
Authorization: Bearer <SIMORGH_DEVICE_TOKEN>
```

The AvalAI API key remains exclusively on Simorgh Core. Android receives only a separate device-gateway token.

## Connection lifecycle

```text
Android foreground service       Simorgh Core
   |--- WebSocket -------------------->|
   |--- device.register -------------->|
   |<-- device.registered -------------|
   |--- heartbeat -------------------->|
   |<-- heartbeat_ack -----------------|
   |--- device.observation ----------->|
   |<-- device.observation_ack --------|
   |<-- device.action_command ---------|
   |--- device.action_command_ack ---->|
   |--- device.action_result --------->|
   |<-- device.action_result_ack ------|
   |<-- device.action_cancel ----------|
   |--- device.action_cancel_ack ----->|
```

The first application message must be `device.register`. Core rejects an unregistered connection, an invalid device identifier, an unsupported protocol envelope, or an invalid bearer token.

The WebSocket is owned by `SimorghConnectionService`, not the Activity. Closing the Android UI therefore does not intentionally terminate the device session.

## Protocol envelope

Every message contains:

- `protocol_version`;
- globally unique `message_id`;
- typed `type`;
- `sent_at_ms`;
- `device_id`;
- optional `correlation_id`;
- structured `payload`.

Current protocol version: `1.0`.

Inbound Core messages are rejected when their UTF-8 byte length exceeds the protocol limit, `message_id` is not a UUID, the timestamp is invalid, the device identity differs, or the typed payload cannot be decoded.

## Resilience

The Android client implements:

- registration before normal traffic;
- WebSocket-level pings;
- application heartbeat negotiated by Core;
- bounded exponential reconnect delay from 1 to 30 seconds;
- a bounded generic outbound queue of 100 messages;
- connection generations that discard callbacks from obsolete sockets;
- replacement of an older live connection when the same device reconnects;
- sticky foreground-service recovery after ordinary process eviction;
- optional restoration after device boot;
- ordered latest-wins Accessibility observations with explicit acknowledgements;
- encrypted write-ahead action state;
- stable action result delivery after reconnect;
- exact Core command-envelope replay;
- separate command, result, and cancellation correlation.

A connection is marked `CONNECTED` only after Core returns `device.registered`.

Observation and action-result messages intentionally bypass the generic reconnect queue. Their publishers own coalescing or stable retry semantics so queue eviction cannot silently corrupt observation ordering or result identity.

See:

- [`OBSERVATION_TRANSPORT.md`](OBSERVATION_TRANSPORT.md);
- [`ANDROID_ACTION_TRANSPORT.md`](ANDROID_ACTION_TRANSPORT.md).

## Local development

Create `.env`:

```dotenv
SIMORGH_DEVICE_TOKEN=<long-random-device-token>
SIMORGH_OPERATOR_TOKEN=<different-long-random-operator-token>
SIMORGH_HOST=0.0.0.0
SIMORGH_PORT=8080
```

The two tokens must be different:

- the device token authenticates the phone WebSocket;
- the operator token authorizes the Core action API.

Run Core:

```bash
uvicorn simorgh_core.app:app --host 0.0.0.0 --port 8080 --reload
```

### Android emulator

Use:

```text
ws://10.0.2.2:8080/v1/devices/ws
```

### Samsung Galaxy A53 or another physical phone

1. Connect the phone and development computer to the same trusted network.
2. Find the computer's LAN address, for example `192.168.1.20`.
3. Allow inbound TCP port 8080 in the computer firewall for the trusted network only.
4. Enter this endpoint in the debug app:

```text
ws://192.168.1.20:8080/v1/devices/ws
```

5. Enter the value of `SIMORGH_DEVICE_TOKEN` in the app and start the service.
6. Enable the Simorgh Accessibility observer to begin read-only UI snapshots.
7. Use `SIMORGH_OPERATOR_TOKEN` only from the trusted Core/operator client when testing typed action dispatch.

The debug manifest permits cleartext `ws://` for local development. The production manifest disables cleartext traffic and requires `wss://`.

## Secret handling

The device token is encrypted with an AES-GCM key generated and retained by Android Keystore. SharedPreferences contain only ciphertext, its IV, the endpoint, and service preferences. The AES key is non-exportable through the application API.

The active action ledger uses a separate Android Keystore-backed AES-GCM key and contains encrypted typed command/result state. The endpoint is not considered a secret. The AvalAI and operator tokens are never sent to or stored on Android.

This is a transport credential foundation, not the final pairing system. A later increment will replace the shared development device token with device-specific, revocable credentials.

## Foreground service behavior

The connection service is user-visible and has an ongoing notification with a Stop action. Android 14 and newer use the declared `specialUse` foreground-service type. Starting after device boot is controlled by an explicit switch and is independent of sticky process recovery.

The foreground service owns the WebSocket, observation publisher, action router, encrypted ledger, and result publisher. No network or planning work runs inside Accessibility callbacks.

See [`ANDROID_ALWAYS_ON.md`](ANDROID_ALWAYS_ON.md) for Android-version behavior, Samsung setup, and physical-device validation scenarios.

## Current scope and next step

The device channel now supports registration, heartbeat, ordered read-only Accessibility observations, typed action command delivery, command acknowledgement, cancellation, result delivery, result acknowledgement, and crash-safe replay semantics.

No Android side-effect adapter is installed by this transport increment. The next vertical slice implements only `open_app`, verifies it using a newer Accessibility observation, and rejects all other operations until their own implementation and evidence are merged.
