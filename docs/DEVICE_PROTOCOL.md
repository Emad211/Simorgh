# Device Protocol

## Status

- Protocol version: `1.0`
- Transport implementation: planned in issue #3
- Schema source of truth: shared versioned contracts, not ad-hoc WebSocket payloads

## Purpose

The device protocol connects Simorgh Core with one or more paired execution devices. It carries capability advertisements, observations, commands, progress events, action results, cancellation, and diagnostics.

The protocol separates planning from execution: Core sends typed actions; Android never receives raw natural-language instructions for direct execution.

## Envelope

Every message will use a common envelope:

```json
{
  "protocol_version": "1.0",
  "message_id": "uuid",
  "correlation_id": "uuid",
  "device_id": "opaque-device-id",
  "sent_at": "2026-07-24T12:00:00Z",
  "type": "device.capabilities",
  "payload": {}
}
```

## Initial message families

### Device to Core

- `device.hello`
- `device.capabilities`
- `device.heartbeat`
- `device.observation`
- `action.started`
- `action.progress`
- `action.result`
- `device.error`

### Core to device

- `device.welcome`
- `action.execute`
- `action.cancel`
- `observation.capture`
- `device.configure`

## Capability advertisement

Capabilities are explicit strings with optional versioned metadata. Examples:

```json
{
  "capabilities": {
    "android.launch_app": {"version": "1"},
    "android.accessibility_tree": {"version": "1", "enabled": false},
    "android.gesture": {"version": "1", "enabled": false},
    "android.screen_capture": {"version": "1", "enabled": false}
  }
}
```

Core validates each plan against the latest advertised device capabilities before dispatch.

## Delivery semantics

- Messages have unique IDs.
- Commands support idempotency keys where repeating an operation could create duplicate state.
- The device acknowledges accepted commands before execution.
- Results remain queued locally until acknowledged by Core.
- Reconnection sends the last acknowledged sequence and resumes delivery.
- Cancellation is best-effort for the currently running atomic device operation and mandatory between plan steps.

## Compatibility

- Minor additive changes preserve the same protocol major version.
- Removing or changing field meaning requires a major-version change.
- Unknown optional fields are ignored.
- Unknown required message types are rejected with a structured error.
- Capability negotiation prevents sending unsupported actions to older devices.

## Planned transport

A persistent WebSocket over TLS is the initial transport. Device pairing, authentication, replay protection, reconnect behavior, and local queue persistence are implemented before accessibility execution is enabled.
