# ADR 0015: Durable invocation identity, reservation and exact replay

- Status: Proposed
- Date: 2026-07-25
- Governing directive: `docs/SIMORGH_MASTER_DIRECTIVE.md`
- Parent implementation issue: #36
- Step issue: #38
- Implementation PR: #39

## Context

ADR 0014 made task identity and routing state durable. Model and tool invocation identity remained process-local.

That left several unacceptable gaps for a permanent personal colleague:

- a completed call could not replay after Core restart;
- an invocation interrupted after a provider/tool might accept it could be issued again;
- worst-case reserved cost was not a durable fact;
- provider/tool result identity and actual usage were not integrity-checked across restart;
- an uncertain mutation had no separate terminal state;
- parent task cost could remain lower than crash-recovered invocation cost;
- the direct model endpoint bypassed the governed budget/invocation gateway.

Future specialist execution, Scheduled Missions, Channels, Delegation and Android operations all require one native invocation authority before they can safely execute work.

## Decision

Simorgh introduces one versioned native invocation contract shared by model, tool and future specialist calls.

Production storage is a separate SQLite WAL database configured through:

```text
SIMORGH_INVOCATION_STORE_PATH
```

The invocation store is independent from the task store and Android action journal.

### Immutable identity

Every invocation binds:

```text
invocation_id
request_id
agent_id and version
operation
canonical input fingerprint
kind and effect class
provider/model or tool/connector target
optional parent invocation
attempt number
creation time
```

The invocation ID cannot be rebound to changed identity or input.

### Kinds and effects

Kinds:

```text
model
tool
specialist
```

Effects:

```text
read_only
proposal
mutation
```

Availability or schema does not grant execution permission. Gateways enforce task and specialist policy before claiming an invocation.

### State machine

```text
pending
reserved
completed
failed
cancelled
expired
unknown
unknown_side_effect
```

`unknown_side_effect` is reserved for uncertain mutation invocations. It is terminal and cannot be automatically retried.

### Reserve before external call

Gateways use this order:

```text
durable pending claim
    ↓
request-budget reserve
    ↓
durable invocation reserve
    ↓
provider/tool call
```

If durable reservation fails, the request-budget reservation is released and no external call occurs.

The durable reservation contains the same worst-case `UsageVector` that guarded the external call.

### Completion

A completed invocation stores:

- typed result payload;
- result SHA-256;
- actual or conservative committed usage;
- immutable target and invocation identity.

The payload is limited to 1,000,000 canonical JSON bytes.

### Exact replay

An exact completed invocation replay:

- returns the prior typed result;
- performs zero new external calls;
- performs zero new budget reservations;
- adds zero token/tool/cost usage;
- keeps result and invocation identity unchanged.

The gateway validates the stored result identity and committed usage before returning it.

### Recovery

At startup:

```text
pending → unknown with zero additional usage
reserved read/proposal → unknown with reserved usage committed
reserved mutation → unknown_side_effect with reserved usage committed
```

No interrupted invocation is automatically retried.

### Failure accounting

A provider/tool exception after durable reservation commits conservative reserved usage because the remote service may have accepted the request.

Only bounded typed failure metadata is stored. Provider/tool exception messages are not persisted; gateways record the exception class name.

A coroutine cancellation after reservation marks the invocation unknown, commits conservative usage and re-raises `CancelledError`.

### Task aggregate reconciliation

Invocation records are detailed cost authority; task records are parent aggregates.

During Core startup, committed invocation usage is summed by `request_id`. Each retained parent task budget is raised component-wise to at least that total.

This merge is idempotent:

- existing task usage never decreases;
- already-accounted invocation usage is not added twice;
- multiple invocation records are summed;
- over-limit recovered usage marks the task budget exhausted;
- missing/pruned parent tasks are not recreated.

### Result privacy

Result payload is durable operational data, not a trace.

It may contain only the approved typed result contract. Raw source bodies, credentials, tool arguments and provider error messages are prohibited.

Validation failures are converted to generic invocation state errors so private payload values are not echoed by Pydantic error rendering.

The SQLite database is integrity-checked but not application-level encrypted in this increment.

### Direct model bypass

The legacy `POST /v1/model/text` endpoint bypassed budgets and invocation durability. It is now operator-bound and returns HTTP 410 until a fully governed API is designed.

### Retry

No retry API is enabled by this ADR.

The schema reserves `parent_invocation_id` and `attempt` for future explicit retry chains. Any retry must use a new ID, new budget reservation and an unchanged terminal parent. Unresolved mutations cannot be retried.

### Store health

SQLite uses:

```text
WAL
synchronous=FULL
foreign_keys=ON
busy_timeout=5000
canonical JSON + SHA-256
indexed-column cross-checks
schema metadata
integrity_check
```

A durable database failure latches the store unhealthy. No stale process-local fallback is permitted.

One active Core process owns one invocation-store path.

## Consequences

### Positive

- model and tool completion replay survives restart;
- completed replay creates no duplicate call or charge;
- worst-case cost is durable before the external boundary;
- interrupted calls recover honestly;
- uncertain mutations receive an explicit stronger terminal state;
- provider/tool private error text is not stored;
- result identity and actual usage are immutable;
- task-level cost is reconciled with invocation truth;
- future specialist execution can use one established contract;
- ordinary CI remains fake/local and cost-free.

### Negative

- every governed external call adds SQLite writes;
- result payloads increase database size;
- there is no terminal pruning policy yet;
- result payloads are not application-level encrypted;
- no automatic or explicit retry API exists;
- task cancellation is not fully propagated to all child invocations until Phase 1 Step 1.6;
- a result-store failure after provider success remains an unknown call on restart;
- a missing retained parent task cannot display aggregate cost even though the invocation record remains authoritative;
- multi-process Core operation is not supported.

## Rejected alternatives

### Keep invocation state process-local

Rejected because crash-safe replay and uncertainty accounting would be impossible.

### Retry pending/reserved calls automatically after restart

Rejected because the provider, connector or mutation target may already have accepted the request.

### Persist only completed results

Rejected because the system would have no durable evidence that a call crossed the reservation boundary before crash.

### Release reserved cost after crash

Rejected because it would treat potentially accepted external work as free.

### Put invocation rows in the task store

Rejected because task aggregation and individual external-call identity have distinct state, integrity and recovery semantics.

### Put model/tool calls in the Android action journal

Rejected because Android evidence and remote provider/tool uncertainty are separate domains.

### Store raw provider/tool exceptions

Rejected because exception messages can contain prompts, arguments, source text or secrets.

### Keep the direct model endpoint

Rejected because it bypassed stable identity, model pricing policy and pre-call budget reservation.

### Implement retry in the same PR

Rejected because retry introduces a separate authorization, budget and mutation-safety boundary.

## Validation requirements

Before acceptance, automated tests must prove:

- SQLite round trip and immutable identity;
- completed model replay after reopen with provider call count unchanged;
- completed tool replay after reopen with invoker count unchanged;
- replay leaves a fresh request budget untouched;
- durable invocation reservation exists before provider/tool entry;
- pending recovery to unknown;
- reserved recovery with conservative usage;
- mutation recovery to unknown-side-effect;
- task aggregate usage reconciliation without double count;
- task overage/exhaustion recovery;
- cancellation and expiry persistence;
- result and usage immutability;
- payload-size rejection without private error echo;
- provider/tool exception-message redaction;
- payload hash and indexed-column tamper detection;
- unsupported schema startup failure;
- application lifespan recovery and unwind;
- direct ungoverned model endpoint disabled;
- Core Ruff, strict MyPy and all tests;
- Android build, JVM tests, lint and APK;
- no live provider, connector or MCP call in ordinary CI.

## Follow-up

After this ADR is accepted, Phase 1 continues with:

1. specialist execution interface;
2. typed specialist result and artifact model;
3. governed GitHub read connector workflow;
4. task-to-invocation cancellation propagation;
5. context compiler and compaction;
6. durable end-to-end trace;
7. explicitly budgeted live-provider staging validation.
