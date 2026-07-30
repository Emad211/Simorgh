# Simorgh specialist-agent runtime

Status: typed routing and policy foundation merged in PR #30; durable task authority merged in PR #37; durable invocation authority merged in PR #39; zero-external specialist execution merged in PR #44; typed result/evidence authority merged in PR #48; governed GitHub read authority merged in PR #52; durable cancellation propagation merged in PR #54; deterministic Context Compiler merged in PR #56; durable correlated trace merged in PR #60. Phase 1.9 live-provider staging is active in issue #65. The default execution API remains routing-only.

## Purpose

The specialist runtime selects one primary owner for a typed task while enforcing predictable cost, privacy, tool access, crash recovery and execution boundaries.

It is not an unrestricted autonomous loop and it is not a replacement for Android action contracts.

## Runtime flow

```text
TaskEnvelope
    ↓
durable task identity / replay / deadline
    ↓
SpecialistRouter
    ├── explicit task kind
    ├── deterministic Persian/English rules
    └── optional one-call classifier
           ↓
       durable model invocation
           ↓
RoutingDecision
    ↓
deterministic taint-aware Context Compiler
    ↓
internal typed specialist execution
    ↓
durable specialist invocation result or honest terminal uncertainty
    ↓
immutable typed result / artifact / evidence metadata authority
    ↓
durable correlated trace audit projection
```

The current `POST /v1/agent-tasks` endpoint performs durable routing only. It does not automatically invoke the selected specialist, connector or Android action. PR #44 merged an internal control-plane method for one zero-external specialist; it is not exposed as a public execution endpoint. PR #48 adds an internal result terminalization boundary and does not expose a public result endpoint.

## Native durable authorities

Six independent operational stores exist:

```text
AgentTaskStore
  task identity, routing state, task budget, cancellation and expiry

InvocationStore
  model/tool/specialist call identity, reservation, execution payload and uncertainty

ResultStore
  immutable final typed result, artifact/evidence metadata, privacy, retention and replay

ContextStore
  immutable compiled specialist context, exact schemas, taint, omissions and replay

TraceStore
  source-linked event sequence, current status, gaps, replay and privacy-safe audit reconstruction

AndroidActionJournal
  device command delivery, ACK, result and Android side-effect uncertainty
```

They are intentionally separate because their identities, state transitions, recovery rules and evidence differ.

## Authentication

Agent-task APIs use:

```text
Authorization: Bearer <SIMORGH_OPERATOR_TOKEN>
```

The Android device token is not accepted. Model-provider credentials are not accepted from clients and remain on Core.

The legacy direct model endpoint is also operator-bound but returns HTTP 410 because it does not define a task budget, model catalog or invocation policy.

## Agent-task API

### Submit or replay a task

```http
POST /v1/agent-tasks
Authorization: Bearer <operator token>
Content-Type: application/json
```

Example:

```json
{
  "schema_version": "1.0",
  "request_id": "11111111-1111-1111-1111-111111111111",
  "received_at_ms": 1784990000000,
  "deadline_at_ms": 1784990060000,
  "locale": "fa-IR",
  "input_text": "ریپازیتوری GitHub پروژه را بررسی کن",
  "requested_outcome": "گزارش ساختاریافته وضعیت ریپازیتوری",
  "explicit_task_kind": "repository_research",
  "risk_class": "read_only",
  "freshness": "current",
  "latency": "interactive",
  "execution_mode": "read_only",
  "allowed_data_sources": ["github"],
  "budget": {
    "max_model_calls": 0,
    "max_tool_calls": 4,
    "max_input_tokens": 4000,
    "max_output_tokens": 1000,
    "max_estimated_cost_microusd": 0,
    "max_elapsed_ms": 30000,
    "max_retries": 0,
    "max_parallel_branches": 1
  }
}
```

An exact retry with the same `request_id` and identical canonical content returns the retained durable record and routing decision. It does not route again.

Reusing a request ID with different content returns HTTP 409.

### Read status

```http
GET /v1/agent-tasks/{request_id}
Authorization: Bearer <operator token>
```

### Cancel future work

```http
POST /v1/agent-tasks/{request_id}/cancel
Authorization: Bearer <operator token>
Content-Type: application/json

{"reason":"کاربر از طریق Voice گفت لغو"}
```

Cancellation is idempotent and survives restart. Phase 1.6 first persists the task cancellation request and cancelled budget, then installs a durable invocation fence, captures the exact ownership snapshot, signals registered cooperative owners, settles pending work and handles reserved work with typed proof or conservative uncertainty.

A reserved read/proposal becomes `cancelled` only when an adapter proves external execution was not entered and releases the reservation; otherwise it becomes `unknown` with conservative committed usage. Reserved mutation always becomes `unknown_side_effect`. Completed results and committed cost remain immutable. See [`CANCELLATION_PROPAGATION.md`](CANCELLATION_PROPAGATION.md) and ADR 0019.

## Durable cancellation propagation

The task store remains cancellation source of truth and the invocation store owns a derived fence keyed by `request_id`. Invocation `begin` and `reserve` fail closed after the fence. Work that wins the race before the fence is included in the deterministic ownership snapshot and settled.

Process-local owner and adapter registries are optional responsiveness mechanisms only. They are exactly-once, late-registration-blocked and empty after restart. Disabling adapter hooks preserves durable fencing, pending cancellation and conservative reserved uncertainty. Audit events contain IDs, states, counts and hashes; operator reason, task content, prompts, connector bodies, exception messages and credentials are excluded.

## Task phases

```text
routing
routed
needs_clarification
needs_escalation
budget_exhausted
policy_blocked
contract_invalid
cancelled
expired
unknown
```

`routed` means a specialist was selected. It does not mean the requested work or external side effect completed.

A `routing` record found after Core restart becomes `unknown`; it is not automatically routed again.

## Task identity and deadlines

A task fingerprint is calculated from canonical typed content, including sorted data-source identities.

A durable `routing` claim is written before the Router is called. If that write fails, no Router, classifier, model or tool path is entered.

Absolute task deadlines are checked before routing. The request budget's monotonic elapsed limit is reduced to the stricter of:

```text
configured max_elapsed_ms
absolute deadline remaining at submit time
```

An already expired task receives phase `expired` and never enters Router, model or tool paths.

## Deterministic Persian-first routing

Normalization includes:

- Unicode NFKC;
- Arabic/Persian yeh and kaf normalization;
- selected Arabic letter variants;
- ZWNJ/ZWJ whitespace handling;
- case folding;
- punctuation and whitespace normalization.

Rules match normalized phrase boundaries rather than arbitrary substrings. A phrase such as `api` therefore does not match inside an unrelated larger token.

Routing priority resolves an otherwise equal deterministic score when one specialist has a uniquely stronger compiled priority.

Examples routed without a model:

```text
ریپازیتوری GitHub و pull request ها را بررسی کن
    → github.read

برای سئوی سایت و سرچ کنسول برنامه بده
    → seo.planner

کمپین و قیف فروش را طراحی کن
    → marketing.planner

قرارها و زمان آزاد امروز را بخوان
    → calendar.read
```

## Ambiguity

When deterministic routing does not produce one unique owner:

- without a classifier, the result is `needs_clarification` with zero model calls;
- with a configured classifier, at most one stable invocation is permitted;
- low confidence returns `needs_clarification`;
- invalid classifier JSON returns `contract_invalid`;
- provider failure returns `needs_escalation`;
- budget failure returns `budget_exhausted`.

`model_calls` reports committed calls, not merely an attempted code path. A budget rejection before provider invocation therefore reports zero model calls.

If a classifier invocation is interrupted after durable reservation, its invocation becomes `unknown`, its conservative usage survives, and its parent routing task becomes or remains `unknown`.

## Specialist policy

A specialist definition contains:

```text
agent_id / version
task kinds and locale prefixes
input and output contracts
tool allowlist
connector allowlist
model tiers and call ceiling
budget ceiling
side-effect policy
routing rules and priority
escalation targets
```

The effective invocation budget is the intersection of the request budget and specialist ceiling.

### Current specialists

```text
github.read
development.planner
seo.planner
marketing.planner
gmail.read
calendar.read
drive.read
mobile.planner
general.planner
```

Current policies are intentionally narrow. Read specialists use read-only connectors. Planning specialists emit proposals and cannot execute mutations.

## Durable invocation contract

Invocation kinds:

```text
model
tool
specialist
```

Effect classes:

```text
read_only
proposal
mutation
```

States:

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

Identity binds the parent task, agent/version, operation, canonical input fingerprint, kind/effect and provider/model or tool/connector target.

Completed execution payloads are immutable, typed, hashed and limited to one million canonical JSON bytes. The separate final result authority has its own smaller inline limit and schema registry.

At restart:

```text
pending → unknown
reserved read/proposal → unknown + conservative committed usage
reserved mutation → unknown_side_effect + conservative committed usage
```

No automatic retry is enabled. Phase 1.6 permits explicit same-task child identity only after a terminal parent and with the exact next attempt number; this ownership relation does not authorize automatic redispatch.

## Model gateway

The governed model gateway:

1. selects the cheapest enabled model in the lowest allowed sufficient tier;
2. durably claims invocation identity;
3. reserves worst-case request budget;
4. persists the same worst-case invocation usage;
5. calls the provider once;
6. reconciles provider-reported or conservative usage;
7. validates provider and model identity;
8. validates selected output-token limit;
9. persists one typed completed or terminal invocation;
10. replays exact completed results after restart without another provider call or budget reservation.

A transport exception after reservation commits conservative usage because the provider may already have accepted the request.

Provider exception messages are not persisted. Only bounded failure metadata and the exception class are retained. Prompt and instructions are absent from invocation records and traces.

A cancelled provider coroutine marks the invocation unknown and re-raises `CancelledError`.

The default agent-task API does not instantiate a live model classifier. Enabling one requires an explicit catalog, pricing, policy hash, provider configuration and budget.

## Tool gateway

The governed tool gateway checks:

```text
active specialist/version
task allowed_data_sources
specialist tool allowlist
specialist connector allowlist
side-effect policy
stable invocation identity
remaining tool budget
```

It claims and reserves durable invocation state before calling the structured tool.

The current gateway executes read-only structured tools only. Mutation calls are blocked before invocation claim even if a future executor specialist exists; each mutation domain requires a separately reviewed typed executor.

Exact completed read-tool calls replay after restart without invoking the connector or consuming a new budget.

Phase 1.5 adds a Core request compiler and reviewed GitHub manifest for exactly `github.search`, `github.fetch-file`, `github.fetch-issue` and `github.fetch-pr`. Current/execution-bound tasks require live fresh evidence; cached tasks remain policy-bounded. Typed projections are hash/byte bound and always tainted. Private, stale, oversized, binary-content or traversal-widening responses fail closed. Deterministic post-call rejection is a sanitized failed invocation with committed usage; transport uncertainty remains unknown.

Tool arguments and raw connector responses are not copied to traces. Provider/tool exception messages are not persisted. See [`GOVERNED_GITHUB_READ_TOOLS.md`](GOVERNED_GITHUB_READ_TOOLS.md) and ADR 0018.

## Context Compiler

PR #56 adds a zero-external compiler between routing and specialist execution. It intersects the durable task/routing record, exact specialist policy, capability subset, remaining budget, reviewed tool schemas, registered output schema and approved task-bound materials into one immutable `SpecialistContextBundle`. User and external evidence remain tainted data; policy and schemas remain top-level typed authority.

Compilation is deterministic across material and tool-schema permutations, records typed omissions/truncations, applies distinct project/decision/evidence limits, rejects concrete credential-shaped material without echo and replays from a retention-aware SQLite authority. Cancellation/deadline fences are checked before assembly, before claim and after claim. Compilation consumes no model/tool/connector/specialist call and creates no usage reservation. The schema-only repository-report family enables `github.read` context validation but does not implement the Phase 1.10 report executor or presentation. See [`CONTEXT_COMPILER.md`](CONTEXT_COMPILER.md) and ADR 0020.

## Specialist execution runtime

The native specialist runtime accepts only a durable `routed` task record, resolves the exact compiled specialist version, restores the durable budget snapshot, rejects widened/exhausted budgets, and derives a stable specialist invocation identity.

The initial implementation executes only deterministic local proposal specialists with zero model calls, zero tool calls and zero external cost. Capabilities are selected by Core; clients cannot submit arbitrary tools, connectors, model tiers or mutation authority.

The Phase 1.3 result family is a concrete `SpecialistPlanPayload`; arbitrary final dictionaries and raw model text are rejected. Each request binds a stable context-bundle identity, a per-invocation cancellation-owner identity, the effective budget and its monotonic timeout.

Completed execution results are stored as `InvocationStore(kind=specialist)` records and replay after SQLite reopen without re-entering the executor. Replay remains valid after the original deadline or removal of the in-process executor because no work is repeated. Changed context, policy, capability, budget or output identity conflicts under the same invocation ID.

Cancellation before durable completion becomes a durable cancelled/unknown state as appropriate. Absolute and monotonic deadlines are checked before and after executor entry. Specialist start, completion, failure and replay traces contain bounded authority metadata only and remain process-local. Typed mutation policies remain disabled and require a separate reviewed executor boundary. See [`SPECIALIST_EXECUTION.md`](SPECIALIST_EXECUTION.md) and ADR 0016.

## Typed result and artifact authority

Phase 1.4 terminalization loads the completed specialist invocation, verifies its exact typed payload and committed usage, resolves an exact result-schema version, and claims one immutable `AuthoritativeSpecialistResult` in a separate `ResultStore` before reporting result-authority success.

The initial family is `simorgh.typed-plan.v1` → `simorgh.specialist-plan-result` schema `1.0`. Artifact bytes and raw connector bodies remain outside the authority; only bounded hash-addressed artifact metadata and tainted evidence projections are admitted. Effective result privacy and retention cannot be weaker than linked references.

SQLite restart replay returns the identical result ID and canonical hash without re-entering the specialist or charging new usage. Persian presentation is rendered deterministically outside authority fields and cannot alter the result hash. See [`TYPED_RESULTS.md`](TYPED_RESULTS.md) and ADR 0017.

## Task and invocation cost reconciliation

The invocation store is detailed per-call cost authority. The task store is the parent aggregate.

At startup:

```text
sum committed invocation usage by request_id
    ↓
raise retained parent task usage component-wise
    ↓
never decrease existing task usage
    ↓
do not double-count already-accounted calls
    ↓
mark over-limit recovered budgets exhausted
```
