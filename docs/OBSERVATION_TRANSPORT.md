# Android observation transport

Status: implementation candidate for review

This document defines how a bounded, redacted Android Accessibility snapshot moves from the private Simorgh Android client to Simorgh Core. It is the observation half of the future observe-plan-act-verify loop.

## Goals

The transport must:

- preserve Persian and mixed Persian-English UI semantics;
- keep Accessibility callbacks free of network and hashing work;
- transmit only bounded, schema-valid snapshots;
- prefer the newest device state over stale intermediate states;
- survive transient WebSocket loss without reporting false success;
- distinguish a retry from a newer unchanged snapshot;
- remain idempotent when the phone reconnects;
- verify the state fingerprint independently in Core;
- expose enough ordering metadata for deterministic traces.

## Non-goals

This increment does not:

- click, type, scroll, dispatch gestures, or invoke global actions;
- capture or transmit screenshots;
- persist observations to a database;
- send every Accessibility event;
- provide remote query APIs for UI content;
- treat a received snapshot as permission to act.

## End-to-end path

```text
AccessibilityService
    |
    | debounced local event
    v
bounded AccessibilitySnapshot
    |
    | process-local latest-state bus
    v
SimorghConnectionService
    |
    | background hashing and latest-wins coalescing
    v
AccessibilityObservationPublisher
    |
    | device.observation over authenticated WebSocket
    v
Simorgh Core device gateway
    |
    | schema validation + canonical fingerprint verification
    v
per-device in-memory observation ledger
    |
    | device.observation_ack
    v
Android publisher
```

The Accessibility callback never waits for WebSocket I/O. The foreground connection service keeps an atomic reference to the newest snapshot and drains it on a single background executor.

## Protocol message

`device.observation` uses protocol envelope version `1.0` and contains:

```json
{
  "stream_id": "uuid",
  "sequence": 17,
  "state_fingerprint": "64-character lowercase SHA-256 hex",
  "snapshot": {
    "schema_version": "1.0",
    "snapshot_id": "uuid",
    "captured_at_ms": 1784890000000,
    "active_package": "com.example",
    "active_window_id": 42,
    "root_node_id": "24-character node id",
    "windows": [],
    "nodes": [],
    "truncated": false,
    "truncation_reasons": [],
    "max_depth_observed": 0
  }
}
```

The corresponding `device.observation_ack` contains:

```json
{
  "stream_id": "uuid",
  "sequence": 17,
  "snapshot_id": "uuid",
  "status": "accepted | unchanged | duplicate | stale",
  "received_at_ms": 1784890000500
}
```

The acknowledgement envelope `correlation_id` must equal the observation envelope `message_id`.

## Stream and sequence semantics

A publisher creates one random `stream_id` for its lifetime. Every submitted distinct state receives a monotonically increasing sequence number. Retries reuse all of the following values:

- `message_id`;
- `stream_id`;
- `sequence`;
- `snapshot_id`;
- `state_fingerprint`;
- serialized payload.

A reconnect within the same Android process retains the stream and sequence. A process restart creates a new stream. Core binds one stream to one live device session and rejects a stream change inside that session.

## Acknowledgement statuses

| Status | Meaning | Core state update |
|---|---|---|
| `accepted` | New ordered observation with changed UI state | Replace latest observation |
| `unchanged` | New ordered observation whose canonical state equals the latest state | Refresh latest observation and ordering cursor |
| `duplicate` | Replayed message, snapshot, or identical sequence identity | No semantic state change |
| `stale` | Sequence is lower than the accepted high-water mark | No state update |

`unchanged` is intentionally separate from `duplicate`: an unchanged snapshot can be newer and therefore useful as freshness evidence.

## Reconnect idempotency

Observation state belongs to the device ledger, not the current WebSocket object. Core retains a bounded in-memory set of recent message identities per device. Consequently, retrying the same message after reconnect returns `duplicate` instead of `accepted`.

The ledger also verifies that:

- an obsolete replaced WebSocket cannot mutate current device state;
- a message ID cannot be reused with different content;
- one sequence cannot identify two different observations;
- a live device session cannot switch its stream ID.

The current ledger is process-local. A Core restart clears it. Durable persistence and replay recovery will be added with mission tracing before actions depend on historical observations.

## Canonical state fingerprint

Android and Core independently calculate:

```text
SHA-256(canonical Accessibility state v1)
```

The hash intentionally excludes capture identity and timing:

- `snapshot_id`;
- `captured_at_ms`;
- triggering event type;
- protocol envelope ID and send time.

It includes state-bearing data:

- active package, active window, root and truncation metadata;
- sorted windows and their bounds/state;
- nodes sorted by structural path;
- node identity, text, descriptions, bounds, input type, booleans and actions;
- action IDs and labels in deterministic order.

Values use an explicit type marker and UTF-8 byte-length prefix. This prevents ambiguity from separators inside Persian or user-generated text. A shared golden vector in Python and Kotlin tests prevents silent divergence between implementations.

Core rejects an observation when the supplied fingerprint differs from its independently calculated value.

## Latest-wins backpressure

Accessibility can emit many events during animation, scrolling, typing, and window transitions. Sending every event would waste bandwidth and cause the planner to reason over obsolete states.

The Android publisher therefore enforces:

- one in-flight observation;
- one pending observation;
- replacement of the pending observation by the latest distinct state;
- a minimum 500 ms interval between sends;
- a 10-second acknowledgement timeout;
- at most three acknowledged-send attempts;
- the exact same envelope for retries;
- no generic WebSocket reconnect queue for observation messages.

If the socket becomes unavailable between the connected callback and `send`, the attempt counter is restored and delivery pauses until the next confirmed connection.

## Size and schema limits

Core and Android use a 2,000,000-byte UTF-8 message limit. The limit is measured in bytes, not Unicode code points.

Snapshot defaults remain:

- at most 500 nodes;
- maximum depth 40;
- at most 100 traversed children per node;
- at most 512 characters per semantic field;
- at most 40 actions per node;
- at most 100 window records.

Core validates tree integrity, including:

- unique node IDs;
- valid root metadata;
- parent references within the same snapshot;
- exact parent-child depth and path relationships;
- consistent maximum observed depth;
- consistent truncation flags and reasons;
- redaction of password-node semantic text.

Oversized WebSocket messages receive a structured error and a close with code 1009.

## Sensitive UI data

Before transport, password nodes have these fields removed:

- text;
- content description;
- hint text;
- state description.

The Core schema independently rejects password nodes that contain those fields. This increment does not persist observation bodies and does not log them.

The exclusion of the Simorgh package itself prevents the local diagnostics Inspector from creating a self-observation loop.

## Failure model

| Failure | Android behavior | Core behavior |
|---|---|---|
| Socket unavailable | Pause without consuming a send attempt | No state change |
| Ack timeout | Retry exact envelope, bounded to three sends | Duplicate-safe |
| Invalid fingerprint | Keep connection, report correlated protocol error | Reject observation |
| Invalid tree | Keep connection, report correlated protocol error | Reject observation |
| Oversized message | Do not submit locally when detected | Reject and close if received |
| Replaced session | Reconnect on the new socket | Old socket cannot mutate state |
| Newer pending state | Retain only newest pending state | Accept by stream sequence |

## Test evidence required

Before merge:

- Python lint, strict type checking, and tests pass;
- Android build, lint, and JVM tests pass;
- shared fingerprint golden vector passes in Kotlin and Python;
- replay after WebSocket reconnect returns `duplicate`;
- new unchanged sequence returns `unchanged`;
- lower sequence returns `stale`;
- invalid fingerprint returns a correlated `device.error`;
- Android retry tests use a deterministic manual scheduler;
- debug APK artifact is generated.

## Galaxy A53 physical validation

After installing the debug APK on the Samsung Galaxy A53:

1. Enable the Simorgh Accessibility service.
2. Start the persistent Simorgh connection service.
3. Open several Persian and English applications.
4. Confirm the local Inspector changes active package and node counts.
5. Confirm Core receives at most the configured rate during rapid scrolling.
6. Toggle Wi-Fi off and on and verify the latest state is resent once.
7. Turn the screen off and on and verify reconnection and observation recovery.
8. Confirm password fields never display semantic values in the Inspector or Core trace.
9. Record Android version, One UI version, app versions, command, initial state and result.

## Next boundary

After this transport is merged, the next reviewed increment is the typed Android action executor:

```text
fresh observation -> deterministic selector -> one bounded action -> fresh observation -> post-condition
```

No model-generated free-form text will be delivered directly to the Android executor.
