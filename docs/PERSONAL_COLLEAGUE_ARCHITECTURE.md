# Simorgh personal colleague architecture

Status: target architecture with independently reviewed increments. Only capabilities explicitly marked implemented are live.

## Product promise

Simorgh is a Persian-first permanent colleague for one developer/founder. It should help with development, research, GitHub, SEO, marketing, sales, email, calendar, documents and Android work while preserving predictable cost, privacy and user control.

The target is not one enormous agent prompt. It is a coordinated crew of specialists operating on one durable personal work graph.

## End-to-end architecture

```text
Inputs
  Persian voice / wake word
  Android UI
  notification stream
  operator API
  schedules and structured events
  approved connectors and MCP servers
        ↓
Input specialists
  Wake Agent
  Persian ASR Agent
  Notification Projection Agent
  Structured Event Adapters
        ↓
Typed Task Edge
  locale, risk, freshness, latency, budget, requested outcome
        ↓
Specialist Router
  deterministic first, one primary owner
        ↓
Personal Work Graph
  goals, projects, products, tasks, decisions, evidence, artifacts
        ↓
Specialist Crew
  Development / Research / GitHub / SEO / Marketing / Sales
  Gmail / Calendar / Drive / Notification / Mobile
        ↓
Proposal or read result
        ↓
Permission / approval / freshness / capability / budget checkpoint
        ↓
Typed Executor
        ↓
Authoritative Verifier
        ↓
Persian response, UI card, notification or artifact
```

## Specialist crew

### Development specialist

Responsibilities:

- repository and architecture orientation;
- issue and PR analysis;
- implementation plans;
- CI failure diagnosis;
- code and review artifacts;
- release and migration checklists;
- documentation synchronization.

It may read code and prepare changes. Publishing commits, pushing branches and opening PRs use a separate GitHub mutation executor.

### Research specialist

Responsibilities:

- question decomposition;
- source retrieval;
- evidence and contradiction tables;
- confidence and unknowns;
- freshness windows;
- reusable cited research artifacts.

It cannot replace authoritative current sources with model memory.

### SEO specialist

Responsibilities:

- technical SEO audits;
- keyword and intent mapping;
- content opportunity graph;
- Search Console/analytics interpretation;
- content briefs and experiment proposals;
- anomaly detection.

Publishing content or changing production settings requires a typed executor.

### Marketing specialist

Responsibilities:

- positioning and messaging;
- campaign and channel plans;
- creative briefs;
- funnel analysis;
- experiment design;
- performance summaries.

It cannot spend budget, publish or send outreach directly.

### Sales specialist

Responsibilities:

- lead/account research;
- qualification and priority;
- follow-up queue;
- call/email draft preparation;
- pipeline summaries;
- next-best-action proposals.

Sending, CRM mutation and financial commitments are separate actions.

### Communication specialists

```text
gmail.read / gmail.reply.planner / gmail.send.executor
calendar.read / calendar.plan / calendar.write.executor
drive.read / document.planner / document.write.executor
notification.triage / notification.reply.planner / notification.action.executor
```

Read, plan and execute identities remain separate even when they share one product surface.

### Mobile specialists

```text
mobile.planner
android.open_app.executor       implemented
future click/text/scroll/global-action executors
mobile.verifier
```

Voice or model output never becomes a coordinate or Accessibility action directly.

## Persian voice runtime

Follow-up issue: #31.

```text
Local wake detector
    ↓
bounded audio session and VAD
    ↓
Persian ASR with context vocabulary and N-best alternatives
    ↓
normalization and ambiguity policy
    ↓
TaskEnvelope
    ↓
Specialist Router
    ↓
Persian response composer
    ↓
TTS with interruption support
```

Principles:

- no provider/network call before wake or explicit push-to-talk;
- wake-word engine is replaceable;
- Assistant-role mode and standard foreground fallback are distinct capabilities;
- mixed Persian/English repository, app, API and product names are preserved;
- uncertain sensitive entities require clarification;
- follow-up conversation has a bounded session window;
- barge-in and cancellation stop future work;
- raw audio is not a trace or default memory artifact.

## Notification intelligence

Follow-up issue: #32.

Notification callbacks perform only local capture, projection, redaction, deduplication and queueing.

```text
posted/updated/removed event
    ↓
per-app privacy policy
    ↓
projected typed event
    ↓
rule-based urgency/coalescing
    ↓
optional bounded digest specialist
```

No model call occurs for every notification. OTPs, security values, financial content and unknown private apps use conservative projection by default.

Future actions re-read the exact current notification immediately before invoking one approved action. Drafting a reply and sending it are separate specialists.

## MCP integration

Follow-up issue: #33.

MCP servers are governed providers below specialist policy:

```text
reviewed server manifest
    ↓
transport and protocol negotiation
    ↓
tool discovery
    ↓
schema canonicalization and hash
    ↓
quarantine until approved
    ↓
specialist + server allowlist intersection
    ↓
budgeted call and structured validation
```

Supported target transports are local stdio and remote Streamable HTTP behind adapters.

A server-advertised tool or annotation is not permission. Changed schemas receive new identities and are quarantined. Android never connects directly to arbitrary MCP servers.

## Personal Work Graph

Follow-up issue: #34.

The work graph makes Simorgh persistent without continuous model thinking:

```text
Goal → Project/Product → Decision → Task DAG → Evidence/Artifact → Checkpoint
```

Structured events create or update tasks only when a relevant delta occurs. A model is invoked only when semantic work is required.

### Daily cockpit

A high-value read-only routine should combine:

- today's calendar;
- urgent projected notifications;
- failing CI and PR review items;
- project blockers;
- sales/marketing follow-ups;
- SEO anomalies;
- deadlines;
- actual model/tool/cost usage;
- three evidence-backed priorities.

### Work modes

```text
Focus
Development
Research
SEO
Marketing
Sales
Operations
Do Not Disturb
```

Modes change priority, digest cadence and cost/latency preferences. They never grant permissions or tools.

## Harness strategy

### Native runtime first

Simorgh's native runtime owns:

- task and invocation identity;
- specialist policies;
- budgets;
- permissions and approvals;
- durable work graph;
- execution and verification state;
- traces and privacy boundaries.

### Optional Agent Harness adapters

A Harness adapter may provide:

- Todo/plan execution mechanics;
- context compaction;
- background worker implementation;
- OpenTelemetry integration;
- approval UI integration;
- specialist implementation hosting.

The adapter receives an already typed task and bounded capability set. It cannot create additional budget or execute unlisted tools.

### Optional OpenClaw interoperability

OpenClaw-like interoperability may provide:

- channel adapters;
- paired-node concepts;
- mobile/voice UX inspiration;
- gateway diagnostics;
- a canvas or card surface.

Simorgh should not depend on OpenClaw's session, skill or tool trust model. A future adapter maps external channel/node events into Simorgh typed inputs and maps approved Simorgh results back to the channel.

## Cost architecture

```text
local wake / VAD / normalization       zero provider cost
deterministic routing                  zero model cost
structured connector lookup            tool budget only
small model semantic work              explicit reservation
strong-model escalation                typed reason + remaining budget
side-effect verification               authoritative tool/device evidence
```

There is no continuous paid thought loop. Background work is event-driven, scheduled or explicitly requested.

Every dashboard and task record should expose:

- model calls;
- tool calls;
- input/output tokens;
- estimated/provider-reported cost;
- cache/replay state;
- retries and elapsed time;
- escalation reason.

## Privacy architecture

Memory is separated by purpose:

```text
working memory
bounded episodic history
validated semantic facts with provenance
explicit decision memory
operational task/invocation state
secret references in a separate vault
```

Raw voice, complete notifications, email bodies, documents and Accessibility trees are not automatically permanent memory.

Retrieval is specialist-scoped. Current authorization is never inferred from old memory.

## Delivery sequence

### Implemented

- Android persistent authenticated connection;
- read-only Accessibility observations;
- durable Core/Android action identity and replay;
- verified `open_app`;
- bounded Core clock and monotonic evidence;
- first specialist routing/budget/idempotency foundation on PR #30.

### Next reviewed increments

1. complete and merge #29 / PR #30;
2. Persian voice and wake-word foundation (#31);
3. read-only notification projection and digest (#32);
4. read-only governed MCP registry (#33);
5. durable Personal Work Graph and daily cockpit (#34);
6. one connector/read specialist at a time;
7. one mutation executor at a time with separate verification.

## Non-negotiable boundaries

- no single agent receives every tool;
- no raw model output crosses an external mutation boundary;
- no dynamic MCP or skill discovery grants permission;
- no cloud audio before wake/explicit capture policy;
- no model per notification;
- no automatic send, publish or spend;
- no model-generated Android coordinates;
- no result is considered successful without authoritative evidence;
- no physical Galaxy A53/One UI claim without executing its validation protocol.
