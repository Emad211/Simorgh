# Simorgh specialist-agent runtime

Status: typed routing and policy foundation merged in PR #30; durable task authority merged in PR #37; durable invocation authority merged in PR #39; a zero-external native specialist execution runtime is validating in PR #44. The default API remains routing-only.

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
internal typed specialist execution
    ↓
durable specialist invocation result or honest terminal uncertainty
```

The current `POST /v1/agent-tasks` endpoint performs durable routing only. It does not automatically invoke the selected specialist, connector or Android action. PR #44 adds an internal control-plane method for one zero-external specialist; it is not exposed as a public execution endpoint.

## Native durable authorities

Three independent operational stores exist:

```text
AgentTaskStore
  task identity, routing state, task budget, cancellation and expiry

InvocationStore
  model/tool/future-specialist call identity, reservation, result and uncertainty

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

Cancellation is idempotent and survives restart. It marks the task budget cancelled so later work cannot reserve new usage.

The current runtime has no long-running specialist executor. Complete task-to-child-invocation cancellation enumeration is Phase 1 Step 1.6.

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

Completed results are immutable, typed, hashed and limited to one million canonical JSON bytes.

At restart:

```text
pending → unknown
reserved read/proposal → unknown + conservative committed usage
reserved mutation → unknown_side_effect + conservative committed usage
```

No automatic retry is enabled.

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

Tool arguments and raw connector responses are not copied to traces. Provider/tool exception messages are not persisted.

## Specialist execution runtime

The native specialist runtime accepts only a durable `routed` task record, resolves the exact compiled specialist version, restores the durable budget snapshot, rejects widened/exhausted budgets, and derives a stable specialist invocation identity.

The initial implementation executes only deterministic local proposal specialists with zero model calls, zero tool calls and zero external cost. Capabilities are selected by Core; clients cannot submit arbitrary tools, connectors, model tiers or mutation authority.

The Phase 1.3 result family is a concrete `SpecialistPlanPayload`; arbitrary final dictionaries and raw model text are rejected. Each request binds a stable context-bundle identity, a per-invocation cancellation-owner identity, the effective budget and its monotonic timeout.

Completed results are stored as `InvocationStore(kind=specialist)` records and replay after SQLite reopen without re-entering the executor. Replay remains valid after the original deadline or removal of the in-process executor because no work is repeated. Changed context, policy, capability, budget or output identity conflicts under the same invocation ID.

Cancellation before durable completion becomes a durable cancelled/unknown state as appropriate. Absolute and monotonic deadlines are checked before and after executor entry. Specialist start, completion, failure and replay traces contain bounded authority metadata only and remain process-local. Typed mutation policies remain disabled and require a separate reviewed executor boundary. See [`SPECIALIST_EXECUTION.md`](SPECIALIST_EXECUTION.md) and ADR 0016.

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

If a parent task payload has already been pruned, the invocation record remains authoritative but the deleted task is not recreated automatically.

## Direct model endpoint

`POST /v1/model/text` is disabled with HTTP 410:

```text
ungoverned_model_endpoint_disabled
```

A generic direct provider call has no task budget, pricing policy or stable invocation authority. It will not be re-enabled as a bypass.

## Trace model

Trace events may include:

```text
request/invocation IDs
agent/version
routing method/rule
provider/model/tool identity
cache or replay state
usage and estimated cost
typed outcome and reason
bounded metadata such as connector/effect/tier
```

Trace metadata rejects keys associated with secrets or raw private content, including token, password, authorization, API key, raw input, prompt, context content, result payload, tool arguments/results, email body, document content, audio, notification and Accessibility tree.

Current traces are bounded and process-local. They are diagnostic evidence, not durable task or invocation authority.

## Cost behavior

Common deterministic routing:

```text
model calls = 0
tool calls = 0
estimated model cost = 0
```

Completed invocation replay:

```text
new model calls = 0
new tool calls = 0
new tokens = 0
new cost = 0
```

An interrupted reserved invocation conservatively retains worst-case usage. Startup reconciliation prevents that usage from remaining invisible in a retained parent task.

CI uses fake providers and fake tools only. It must not contact AvalAI, MCP servers, Gmail, GitHub or another paid/external service.

## Retry policy

Retry execution is not enabled.

The invocation schema includes parent identity and attempt metadata for future explicit retry chains, but PR #39 does not create retries. A future retry must use a new invocation ID and new retry/call budget, and cannot proceed while mutation outcome is uncertain.

## Adding a specialist safely

1. Choose one stable `agent_id` and semantic version.
2. Define narrow task kinds and locale support.
3. Define exact input/output contracts.
4. Start with no tools and no model when possible.
5. Add only necessary tool and connector IDs.
6. Choose `NONE`, `PROPOSE_ONLY` or a separately reviewed typed executor policy.
7. Set per-agent model/tool/token/cost/time ceilings.
8. Add deterministic Persian and English routing rules.
9. Add negative routing tests to prevent overlap and substring accidents.
10. Add fake provider/tool restart-replay tests proving no CI spending.
11. Add trace and durable-error tests proving private content is absent.
12. Do not add mutation authority in the same change as a planning specialist.

## Current limitations

- the public API remains routing-only; specialist execution is currently an internal zero-external control-plane method;
- no live semantic classifier is configured by default;
- no explicit retry API exists;
- complete task-to-invocation cancellation propagation is deferred to Step 1.6;
- no MCP server is connected;
- no Voice/Wake-word or Notification event reaches this API yet;
- no proactive task graph or persistent personal memory exists yet;
- no mutation specialist is enabled;
- invocation result payloads are not application-level encrypted;
- the invocation store has no terminal retention policy yet;
- task and invocation stores each support one active Core process per path;
- traces remain process-local;
- Android supports only the separately reviewed `open_app` side effect.

Follow-up issues:

- #36 complete the native runtime and GitHub workflow;
- #40 / PR #44 validate the native specialist execution interface;
- #31 Persian Voice/Wake word;
- #32 Notification intelligence;
- #33 governed MCP registry;
- #34 durable Personal Work Graph and proactive crew.
