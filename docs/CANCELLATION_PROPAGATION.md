# Durable task-to-invocation cancellation propagation

Status: Phase 1.6 implementation is validating in PR #54 under issue #53.

## Purpose

Cancellation in Simorgh is a durable control-plane request. It is not proof that an external model, tool, connector or mutation did not execute.

The Phase 1.6 boundary propagates one accepted task cancellation to every owned nonterminal invocation while preserving honest uncertainty and monotonic cost accounting.

```text
authenticated task cancellation request
  → persist cancelled task + immutable cancellation request
  → install durable invocation admission fence
  → capture deterministic ownership snapshot
  → signal registered process-local owners
  → cancel pending/unreserved invocations
  → request optional adapter cancellation for reserved work
  → settle reserved work conservatively
  → persist immutable cancellation result
  → emit privacy-safe audit metadata
```

No Voice, Notification, MCP, Memory, Work Graph, automatic retry, compensation, live provider cancellation or new Android action is enabled by this step.

## Authority and ownership

The durable `AgentTaskStore` remains the source of truth for task cancellation. The `InvocationStore` owns invocation identity and derives a cancellation fence keyed by the parent task `request_id`.

An invocation ownership record is immutable after claim and includes:

- task `request_id`;
- invocation ID;
- invocation kind and effect;
- state;
- optional parent invocation ID;
- optional cancellation-owner ID;
- creation time;
- terminal disposition.

Owned invocations are enumerated in deterministic `(created_at_ms, invocation_id)` order. The exact snapshot is hashed and stored in the cancellation fence and result.

A child invocation requires an existing terminal parent owned by the same task and an attempt number exactly one greater than its parent. A cross-task parent, missing parent or invalid attempt fails closed.

## Race boundary

Task and invocation durability use separate authorities. The required race property is:

```text
invocation begin/reserve wins before the fence
  → it appears in the accepted ownership snapshot and is settled

cancellation fence wins first
  → later begin/reserve is rejected
```

The task cancellation request is persisted before any process-local signal or adapter cancellation hook runs. Invocation `begin` and `reserve` both check the durable fence under the invocation store lock/transaction.

## Public operator API

The existing operator-authenticated endpoint is:

```http
POST /v1/agent-tasks/{request_id}/cancel
Authorization: Bearer <SIMORGH_OPERATOR_TOKEN>
Content-Type: application/json
```

Example:

```json
{
  "cancellation_id": "11111111-1111-1111-1111-111111111111",
  "reason_code": "operator_requested",
  "reason": "کاربر اجرای این وظیفه را لغو کرد"
}
```

`cancellation_id` is optional. When omitted, Core derives a stable identity from the task, reason code, sanitized operator reason and requester authority.

The response is the durable `AgentTaskRecord`. Its cancellation fields contain the immutable request and final bounded result.

## Idempotency and conflicts

An exact repeated cancellation returns the retained durable result and does not:

- signal an owner twice;
- call an adapter twice;
- release or commit usage twice;
- change terminal invocation state;
- create a new model/tool/specialist call.

Reusing the same task cancellation identity with changed content returns a conflict. A cancellation ID already owned by another task is rejected.

Concurrent identical cancellation requests converge on one authoritative request and one adapter attempt per invocation.

## Process-local owner signals

`CancellationOwnerRegistry` maps `(request_id, cancellation_owner_id)` to one cooperative signal target.

Rules:

- each active owner is signalled at most once;
- duplicate registration with the same target is harmless;
- duplicate identity with a different target conflicts;
- owner removal is identity-checked;
- late registration after a durable fence is immediately signalled and then rejected before work enters;
- restart clears process-local registrations and never pretends old tokens still exist;
- durable task and invocation state remain authoritative.

A failed signal is recorded as a bounded disposition. The exception text is not persisted.

## Optional adapter cancellation

Adapters may implement the narrow typed capability:

```text
cancel(invocation_id, cancellation_owner_id)
  → InvocationCancellationAcknowledgement
```

Supported acknowledgement dispositions are:

```text
accepted
already_terminal
not_supported
not_found
proven_not_entered
uncertain
```

`proven_not_entered` is the only disposition allowed to release the invocation usage reservation, and the acknowledgement must explicitly set `usage_reservation_released=true`.

Capability presence never grants authority. Registration is process-local, must match the durable invocation identity and is blocked after the task fence exists.

The adapter registry can be disabled operationally. Disabling external cancellation hooks does not disable task cancellation, admission fences, pending settlement or conservative uncertainty.

## State-transition matrix

| Prior invocation state | Evidence available | Final state | Usage behavior |
|---|---|---|---|
| `pending` | external entry impossible | `cancelled` | zero new committed usage |
| `reserved` read/proposal | typed proof of non-entry and reservation release | `cancelled` | reservation released; committed usage remains zero |
| `reserved` read/proposal | accepted, unsupported, not found, uncertain or no proof | `unknown` | reserved usage becomes conservatively committed |
| `reserved` mutation | any cancellation acknowledgement | `unknown_side_effect` | reserved usage becomes conservatively committed |
| `completed` | terminal result exists | unchanged | committed result and usage remain immutable |
| `failed` / `cancelled` / `expired` / `unknown` / `unknown_side_effect` | already terminal | unchanged | usage never decreases |

An adapter saying `accepted` proves only that cancellation was requested. It does not prove that external execution did not begin.

## Budget and accounting

Cancellation cannot restore committed cost.

Rules:

- the task budget is durably marked cancelled before propagation;
- later budget reservations fail closed;
- invocation `begin` and `reserve` are fenced;
- pending work contributes no usage;
- a reserved read may release usage only with typed proof of non-entry;
- reserved uncertain work commits its conservative reservation;
- mutation uncertainty always conserves usage;
- duplicate cancellation cannot double-release or double-commit;
- task aggregate usage remains monotonic and is reconciled from durable invocation aggregates after restart.

## Restart behavior

After Core restart:

- the cancelled task and its cancellation request/result reload from `AgentTaskStore`;
- the invocation cancellation fence and ownership snapshot reload from `InvocationStore`;
- future invocation admission remains blocked;
- completed and other terminal invocations remain immutable;
- interrupted reserved work is recovered conservatively;
- process-local owner and adapter handles are empty and are not reconstructed from stale memory;
- an exact cancellation replay returns retained state without a new external attempt.

## Audit and privacy

Cancellation emits `cancellation_settled` or `cancellation_replayed` trace events containing only bounded authority metadata:

- request and cancellation IDs;
- stable audit event ID;
- disposition;
- reason code;
- ownership snapshot SHA-256;
- terminal, pending-cancelled, reserved-cancelled, reserved-uncertain and signalled counts.

Per-invocation cancellation outcomes contain IDs, prior/final state, signal/adapter disposition and a committed-usage hash.

The following are excluded from trace metadata, durable failure detail and cancellation results:

- raw task input or compiled context;
- operator reason text;
- model prompts and responses;
- GitHub file, issue or PR content;
- tool arguments and raw connector responses;
- provider/adapter exception messages;
- credentials, bearer tokens, headers and environment variables.

The operator reason is normalized and bounded in the durable cancellation request but is never copied into cancellation trace metadata.

## Operational disable and incident response

### Disable adapter hooks

Use the process-local `InvocationCancellationAdapterRegistry.disable()` switch when an adapter cancellation implementation is suspected to be unsafe or unreliable.

This preserves the safer behavior:

```text
durable task cancellation
  + invocation admission fence
  + owner signal
  + pending cancellation
  + reserved uncertainty
  - external adapter cancellation calls
```

### Store health failure

If either durable task or invocation authority reports corruption, schema mismatch, lock conflict or an unhealthy latch:

1. stop accepting new task/cancellation work;
2. do not infer cancellation from process-local state;
3. preserve database files and WAL/SHM companions;
4. follow the task/invocation store backup and recovery procedures;
5. restore both authorities from a mutually consistent operational point;
6. rerun integrity and cancellation replay tests before reopening execution.

### Unexpected adapter result

A malformed, mismatched or exception-throwing acknowledgement becomes `uncertain`; its raw payload or exception text is not persisted. Do not retry automatically.

## Validation boundary

Ordinary CI uses deterministic in-memory/SQLite stores and fake cancellation adapters only. It performs no live provider, connector, MCP or GitHub cancellation call.

Acceptance coverage includes:

- exact ownership and parent/child persistence;
- cancellation fence admission blocking;
- pending and reserved state settlement;
- proof-of-non-entry release;
- read and mutation uncertainty;
- concurrent idempotency;
- owner and adapter exactly-once behavior;
- restart replay;
- cost monotonicity;
- private-marker and exception redaction;
- unchanged Phase 1.5 completed GitHub replay;
- full Core Ruff, strict MyPy and tests;
- unchanged Android build, JVM tests, lint and debug APK generation.

See [`validation/phase-1-6-cancellation-propagation.md`](validation/phase-1-6-cancellation-propagation.md) and ADR 0019.

## Current limitations

- adapter cancellation remains optional and process-local;
- no live provider or GitHub cancellation implementation is enabled;
- no distributed/multi-Core cancellation coordinator exists;
- cancellation does not compensate an external mutation;
- retry remains disabled unless a later boundary creates a new explicit identity and budget;
- Phase 1.7 context compilation, Phase 1.8 complete trace, Phase 1.9 live staging and Phase 1.10 complete Persian GitHub reporting remain separate steps;
- Voice, Notification, MCP, Memory and Work Graph remain parked behind Phase 1 completion.
