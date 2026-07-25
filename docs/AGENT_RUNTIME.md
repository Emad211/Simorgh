# Simorgh specialist-agent runtime

Status: first typed control-plane increment implemented in PR #30; provider-backed classification and specialist execution are not enabled by the default API yet.

## Purpose

The specialist runtime selects one primary owner for a typed task while enforcing predictable cost, privacy, tool access and execution boundaries.

It is not an unrestricted autonomous loop and it is not a replacement for Android action contracts.

## Runtime flow

```text
TaskEnvelope
    ↓
Task identity / replay / deadline
    ↓
SpecialistRouter
    ├── explicit task kind
    ├── deterministic Persian/English rules
    └── optional one-call classifier
    ↓
RoutingDecision
    ↓
future specialist invocation / proposal / typed executor
```

The current `POST /v1/agent-tasks` endpoint performs routing only. It does not invoke the selected specialist, model, connector or Android action.

## Authentication

Agent-task APIs use:

```text
Authorization: Bearer <SIMORGH_OPERATOR_TOKEN>
```

The Android device token is not accepted. Model-provider credentials are not accepted from clients and remain on Core.

## API

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

An exact retry with the same `request_id` and identical canonical content returns the existing record and routing decision. It does not route again.

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

Cancellation is idempotent. It marks the task budget cancelled so future model/tool/specialist work cannot reserve new usage.

The first increment has no long-running specialist executor; cancellation establishes the contract used by later Voice, Notification, MCP and Work Graph runtimes.

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
```

`routed` means a specialist was selected. It does not mean the requested work or external side effect completed.

## Task identity and deadlines

A task fingerprint is calculated from canonical typed content, including sorted data-source identities.

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

Examples currently routed without a model:

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
- with a classifier, at most one stable classifier invocation is permitted;
- low confidence returns `needs_clarification`;
- invalid classifier JSON returns `contract_invalid`;
- provider failure returns `needs_escalation`;
- budget failure returns `budget_exhausted`.

`model_calls` reports actual committed classifier calls, not merely an attempted classifier code path. A budget rejection before provider invocation therefore reports zero model calls.

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

## Model gateway

The governed model gateway:

1. selects the cheapest enabled model in the lowest allowed sufficient tier;
2. creates or checks stable invocation identity;
3. reserves conservative input/output/cost usage;
4. calls the provider once;
5. reconciles provider-reported or conservative usage;
6. validates provider and model identity;
7. validates selected output-token limit;
8. stores one typed completed or terminal invocation state;
9. replays exact completed results without another provider call.

A transport exception commits conservative reserved usage because the provider may already have accepted the request.

The default agent-task API does not instantiate a live model classifier. Enabling one requires an explicit catalog, pricing, policy hash, provider configuration and budget.

## Tool gateway

The governed tool gateway checks:

```text
active specialist/version
specialist tool allowlist
specialist connector allowlist
side-effect policy
stable invocation identity
remaining tool budget
```

The first increment executes read-only structured tools only. Mutation calls are blocked even when a future executor specialist exists; each mutation domain must receive its own reviewed typed boundary.

Exact read-only retries may replay the completed typed result. Tool arguments and result payloads are not copied to traces.

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

Trace metadata rejects keys associated with secrets or raw private content, including token, password, authorization, API key, raw input, email body, document content and Accessibility tree.

Current in-memory traces are bounded and process-local. They are diagnostic evidence, not durable task storage.

## Cost behavior

Common deterministic routing:

```text
model calls = 0
tool calls = 0
estimated model cost = 0
```

A selected specialist is not automatically invoked. Future orchestration must create a separate invocation budget and stable invocation identity.

CI uses fake providers and fake tools only. It must not contact AvalAI, MCP servers, Gmail, GitHub or another paid/external service.

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
10. Add provider/tool fake tests proving no CI spending.
11. Add trace tests proving private content is absent.
12. Do not add mutation authority in the same change as a planning specialist.

## Current limitations

- task, invocation and trace stores are process-local;
- the API routes but does not execute specialists;
- no live semantic classifier is configured by default;
- no MCP server is connected;
- no Voice/Wake-word or Notification event reaches this API yet;
- no proactive task graph or persistent personal memory exists yet;
- no mutation specialist is enabled;
- Android supports only the separately reviewed `open_app` side effect.

Follow-up issues:

- #31 Persian Voice/Wake word;
- #32 Notification intelligence;
- #33 governed MCP registry;
- #34 durable Personal Work Graph and proactive crew.
