# ADR 0013: Native specialist-agent runtime and deterministic cost governance

- Status: Proposed
- Date: 2026-07-25

## Context

Simorgh is intended to become a permanent personal colleague for one developer/founder across software development, research, GitHub, SEO, marketing, sales, email, calendar, documents, notifications and Android execution.

A single general-purpose agent with all tools would be easy to prototype but would create unacceptable properties:

- every request could trigger a model call even when an explicit task kind or deterministic rule is sufficient;
- one prompt could mix planning, execution, verification and reporting;
- retries could repeat provider calls or external mutations;
- tool access could expand implicitly through prompt text or dynamic discovery;
- token, latency and monetary cost would be unpredictable;
- private data from one domain could leak into an unrelated specialist context;
- Android clocks, ledgers, replay and postcondition verification could accidentally depend on model output;
- a third-party harness or gateway could become the de facto authority for Simorgh policy and identity.

Modern agent harnesses provide useful patterns such as Todo state, plan/execute modes, context compaction, approvals, background tasks, cancellation and observability. Local-first agent gateways provide useful patterns such as one gateway, multiple channels, paired device nodes, voice surfaces and a mobile work canvas.

These patterns are valuable, but Simorgh needs stronger typed boundaries and must not be locked to one external runtime.

## Decision

Simorgh will implement a native typed specialist-agent control plane. External harnesses, gateways and MCP servers may be connected through reviewed adapters, but they are never the source of Simorgh authorization, durable identity, budget or side-effect truth.

The control plane is divided into deterministic components:

```text
Task Edge
  typed TaskEnvelope

Routing Agent
  explicit kind → deterministic rules → optional one-call classifier

Specialist Registry
  immutable versioned policy, tools, connectors, model tiers and budget ceiling

Budget Agent
  reserve before call → reconcile actual usage → stop on exhaustion

Invocation Agent
  stable identity, exact replay, conflict detection and terminal states

Model Gateway
  cheapest sufficient model, bounded output, provider identity validation

Tool Gateway
  specialist/tool/connector allowlists and planning-versus-mutation separation

Trace Agent
  non-secret routing, cost, tool and outcome metadata

Typed Executors and Verifiers
  separate deterministic side-effect boundaries
```

### One primary owner

Every task is routed to exactly one primary specialist. The router does not broadcast a request to all specialists or all tools.

Subtasks may later form a bounded typed graph, but each subtask still has one owner, one budget and one output contract.

### Deterministic routing first

Routing order is:

```text
explicit task kind
    ↓
deterministic schema/capability/lexical rules
    ↓
needs clarification when ambiguity remains and no classifier is configured
    ↓
at most one bounded semantic classifier invocation
```

Persian and mixed Persian/English normalization is deterministic. Common routes should use zero model calls.

### Cheapest-sufficient model policy

Model tiers are ordered:

```text
FAST → GENERAL → REASONING → DOMAIN
```

A specialist declares allowed tiers and a minimum tier. The gateway selects the cheapest enabled model in the lowest sufficient tier. Escalation requires a typed reason and remaining budget.

Model choice is policy data, not a prompt suggestion.

### Reserve before invocation

Every model or tool call reserves its worst-case allowed usage before invoking the provider or tool. Actual usage is reconciled afterwards.

Tracked dimensions include:

- model calls;
- tool calls;
- input and output tokens;
- estimated cost in integer micro-US dollars;
- elapsed time;
- retries;
- parallel branches.

A call that cannot reserve budget never reaches the provider. If transport fails after a provider may have accepted a request, conservative reserved usage is committed rather than pretending the call was free.

### Stable invocation identity

Model and tool invocations have stable IDs derived from task and operation identity. Exact completed retries replay the prior typed result when safe. Reusing an invocation ID with different content is a conflict.

An uncertain mutation is never repeated merely because an acknowledgement was lost.

### Planning is not execution

Planning specialists may emit typed proposals. They cannot invoke mutation tools.

External mutation uses a separate reviewed pipeline:

```text
planner proposal
    ↓
permission / approval / freshness / capability checks
    ↓
typed executor
    ↓
authoritative verifier
    ↓
typed result
```

Android action contracts, clock leases, ledgers and Accessibility evidence remain deterministic and model-free.

### Trace privacy

Traces may record:

- task and invocation IDs;
- selected specialist/version;
- routing method/rule;
- provider/model/tool identity;
- cache/replay state;
- usage and estimated cost;
- typed outcome and bounded reason.

Traces must not contain raw prompts, tool arguments, provider keys, bearer tokens, email bodies, document contents, notification text, raw audio or Accessibility trees by default.

### Native runtime with optional adapters

Simorgh may later expose a runtime adapter interface:

```text
AgentRuntimeAdapter
  NativeSimorghRuntime
  MicrosoftHarnessAdapter      optional
  OpenHarnessAdapter           optional
  OpenClawChannelNodeAdapter   optional interoperability surface
```

An adapter may execute a typed specialist implementation or expose a channel/node. It cannot change the compiled specialist policy, allocate additional budget, install tools, approve mutations or replace Simorgh durable IDs.

### OpenClaw-inspired boundary

Useful patterns to adopt:

- local-first gateway;
- multi-channel input;
- paired device nodes;
- voice and mobile work surfaces;
- diagnostics and connection health;
- separate sessions/agents.

Patterns not adopted as trust authority:

- dynamic skill installation from natural language;
- one gateway policy replacing Simorgh contracts;
- unrestricted shell/tool execution;
- treating channel identity as mutation authorization;
- using an external session transcript as durable operational state.

### Agent-harness-inspired boundary

Useful patterns to adopt:

- Todo/plan state outside the model context;
- plan and execute modes;
- bounded context compaction;
- background specialist work;
- human approval gates;
- cancellation and observability;
- configurable loop limits.

Patterns not adopted:

- unbounded autonomous loops;
- automatic approval;
- model-selected permissions;
- compaction that may remove budget, approval, evidence or idempotency state;
- harness-native IDs replacing Simorgh task/invocation IDs.

### MCP boundary

MCP is a governed provider layer beneath specialist policy. Tool discovery is not execution permission.

A future MCP registry will require reviewed manifests, protocol negotiation, schema hashes, quarantining changed tools, specialist allowlists, response limits and mutation separation.

### Voice and notification boundary

Voice transcripts and notification events are typed inputs. They are not proof of user intent for a sensitive mutation and are not proof that a side effect completed.

Wake word, audio capture, notification projection and redaction occur locally where possible. Provider/model calls are used only after explicit policy and budget checks.

## Consequences

### Positive

- common Persian routes cost zero model calls;
- model/tool spending is bounded before invocation;
- one specialist cannot silently inherit all connectors;
- retries are idempotent;
- model, tool and Android execution authority remain separate;
- external harnesses can be evaluated without architectural lock-in;
- Voice, Notification and MCP can share the same typed task and budget foundation;
- traces are useful without becoming a private-data lake;
- future proactive work can be event-driven rather than a continuous paid loop.

### Negative

- more contracts and adapters are required than in a single-agent prototype;
- adding a specialist requires policy, budget and test work;
- process-local invocation/task stores are not sufficient for crash recovery and must later become durable;
- ambiguous requests may require clarification instead of immediate action;
- external framework features cannot be enabled merely by installing a package;
- model catalog pricing and provider identity require explicit configuration.

## Rejected alternatives

### One universal agent with every tool

Rejected because cost, privacy, permissions and verification cannot be bounded reliably.

### Use a third-party harness as the Simorgh core

Rejected because runtime upgrades or semantics could change durable identity, approval, budget and replay behavior.

### Fork OpenClaw as the complete product

Rejected because Simorgh requires its own Android execution evidence, Persian-first routing, specialist policies, work graph and cost governance. Interoperability and product inspiration are preferable to a hard fork.

### Route every request with a model

Rejected because explicit task kinds, schemas and Persian lexical rules resolve many requests more cheaply and reproducibly.

### Dynamically trust MCP-discovered tools

Rejected because discovery metadata and annotations are not sufficient authorization.

### Let planners execute their own proposals

Rejected because planning output is not current permission, freshness proof or side-effect verification.

## Initial implementation

Issue #29 and PR #30 establish:

- task/specialist/routing/budget/usage/invocation/trace contracts;
- deterministic Persian-first routing;
- one-call classifier interface;
- specialist registry and policy allowlists;
- budgeted model and tool gateways;
- process-local idempotent task submit/status/cancel API;
- fake-provider and fake-tool tests with zero CI spending.

Follow-up increments:

- #31 — Persian voice, wake word and conversational audio runtime;
- #32 — privacy-safe notification intelligence;
- #33 — governed MCP client registry;
- #34 — durable Personal Work Graph and proactive specialist crew.

## Validation

Before acceptance, automated tests must prove deterministic zero-model routing, one-call ambiguity handling, budget reservation/reconciliation, provider/tool replay, tool-policy enforcement, trace privacy, task API idempotency/cancellation, and fully green Core and Android CI.
