# Android device transport

Status: implemented foundation

The Android application connects to Simorgh Core through an authenticated, versioned WebSocket endpoint:

```text
GET /v1/devices/ws
Authorization: Bearer <SIMORGH_DEVICE_TOKEN>
```

The AvalAI API key remains exclusively on Simorgh Core. Android receives only a separate device-gateway token.

## Connection lifecycle

```text
Android                 Simorgh Core
   |--- WebSocket ---------->|
   |--- device.register ---->|
   |<-- device.registered ---|
   |--- heartbeat ---------->|
   |<-- heartbeat_ack -------|
```

The first application message must be `device.register`. Core rejects an unregistered connection, an invalid device identifier, an unsupported protocol envelope, or an invalid bearer token.

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

## Resilience

The Android client implements:

- registration before normal traffic;
- WebSocket-level pings;
- application heartbeat negotiated by Core;
- bounded exponential reconnect delay from 1 to 30 seconds;
- a bounded outbound queue of 100 messages;
- connection generations that discard callbacks from obsolete sockets;
- replacement of an older live connection when the same device reconnects.

A connection is marked `CONNECTED` only after Core returns `device.registered`.

## Local development

Create `.env`:

```dotenv
SIMORGH_DEVICE_TOKEN=<long-random-token>
SIMORGH_HOST=0.0.0.0
SIMORGH_PORT=8080
```

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

5. Enter the value of `SIMORGH_DEVICE_TOKEN` in the app and connect.

The debug manifest permits cleartext `ws://` for local development. The production manifest disables cleartext traffic and requires `wss://`.

## Secret handling

The current development UI keeps the device token only in process memory. It is not written to SharedPreferences. A later pairing increment will issue device-specific credentials stored with Android Keystore.

The endpoint is not considered a secret and is persisted for convenience.

## Current scope and next step

This transport increment supports registration and heartbeat. Command delivery, acknowledgement, cancellation, replay protection, persistent queues, and action results will be added as versioned message types before Android execution is enabled.
