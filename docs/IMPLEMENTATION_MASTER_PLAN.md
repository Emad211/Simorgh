# Simorgh gated implementation master plan

- Status: Active
- Governing directive: [`SIMORGH_MASTER_DIRECTIVE.md`](SIMORGH_MASTER_DIRECTIVE.md)
- Planning rule: one major trust boundary per pull request
- Cost rule: fake/local providers in ordinary CI; live tests are explicit, budgeted and separately triggered
- Android rule: automated fixtures and physical Galaxy A53 evidence are reported separately

## How this plan is executed

Each step follows the same lifecycle:

```text
Architecture contract
    ↓
Threat and failure model
    ↓
Typed schema and state transitions
    ↓
Pure unit tests
    ↓
Storage/transport/integration tests
    ↓
Operational documentation
    ↓
Full Core + Android CI
    ↓
Review and merge
```

A step is not complete because code exists. It is complete only when its failure semantics, recovery behavior, cost behavior and evidence are testable and documented.

# Phase 0 — Governance baseline

## 0.1 Adopt the master directive

Deliverables:

- authoritative architecture directive in the repository;
- source checksum;
- implementation order;
- explicit trust boundaries;
- change-control procedure.

Gate:

- no active PR contradicts phase order;
- deferred work is preserved but marked as parked.

Status: in progress on `core/durable-agent-task-store`.

## 0.2 Establish roadmap issues

Deliverables:

- Phase 1 issue for durable runtime and GitHub read workflow;
- existing Voice, Notification, MCP and Work Graph issues linked to the directive;
- no duplicate or contradictory roadmap item.

Gate:

- every issue states its authority, prerequisites, trust boundary and Definition of Done.

Status: Phase 1 issue #36 created; PR #35 parked.

# Phase 1 — Complete the native specialist runtime

## 1.1 Durable task store

### Objective

Make task identity, routing state, budget snapshot, cancellation, expiry and replay survive Core restart.

### Design

```text
AgentTaskRecord
    ↓ canonical versioned payload
AgentTaskStoreEntryV1
    ↓ SHA-256 integrity
SQLite WAL
```

### Deliverables

- `AgentTaskStore` protocol;
- `InMemoryAgentTaskStore` for pure tests;
- `SQLiteAgentTaskStore` for runtime;
- versioned metadata table;
- canonical payload hash;
- immutable request ID and task fingerprint;
- validated state-transition rules;
- bounded terminal retention;
- startup load and recovery;
- `routing` crash state converted to `unknown`, never auto-replayed;
- cancellation/expiry persistence;
- settings and app-lifespan integration;
- recovery and backup documentation.

### Required tests

- SQLite round trip;
- exact replay after a new process/store instance;
- same ID/different task conflict;
- cancellation survives restart;
- expiry survives restart;
- unsupported schema fails closed;
- altered payload/hash fails closed;
- invalid transition fails closed;
- terminal pruning never removes nonterminal records;
- interrupted routing becomes `unknown`;
- no model/tool call occurs during load/recovery;
- full Core and Android CI.

### Merge gate

All tests green; PR remains limited to task durability and documentation.

Status: implementation started in issue #36.

## 1.2 Durable invocation store

### Objective

Make model/tool/specialist invocation identity, reservation uncertainty, terminal state and exact replay survive restart.

### Deliverables

- versioned durable invocation entry;
- SQLite WAL store;
- immutable request/agent/version/operation/input identity;
- pending invocation recovery to `unknown` or typed domain-specific recovery state;
- exact completed replay;
- mutation uncertainty cannot retry;
- cancellation and expiry persistence;
- result payload hash and size limit;
- per-invocation provider/tool identity and usage reconciliation.

### Required tests

- completed model/tool replay after restart;
- changed input conflict;
- pending provider call becomes unknown;
- pending mutation cannot re-run;
- corrupted result fails closed;
- cancellation propagation;
- no duplicate charge.

## 1.3 Specialist execution interface

### Objective

Execute one selected specialist through a narrow typed runtime without exposing all tools or provider configuration.

### Contract

```text
SpecialistExecutionRequest
  task identity
  selected specialist/version
  context bundle
  effective budget
  capability subset
  deadline
  output contract

SpecialistExecutionResult
  typed state
  artifact/evidence references
  usage
  reason
  verification requirements
```

### Deliverables

- runtime-neutral interface;
- native implementation registry;
- no-op/fake implementations;
- model-backed implementation adapter;
- cancellation token;
- stable specialist invocation ID;
- policy intersection before execution.

## 1.4 Typed result and artifact model

### Objective

Separate natural-language presentation from durable structured results and evidence.

### Deliverables

- typed specialist result;
- artifact identity/hash/media type;
- evidence reference with provenance/freshness;
- user-facing Persian rendering kept outside authority fields;
- output schema validation;
- truncation/size policy;
- immutable completed result.

## 1.5 Governed read-only tool execution

### Objective

Let a specialist perform authoritative reads while preserving task, specialist, connector and tool policy intersections.

### Enforcement

```text
task allowed_data_sources
∩ specialist connector_allowlist
∩ specialist tool_allowlist
∩ server/connector policy
∩ remaining budget
```

### Deliverables

- read-only connector interface;
- freshness and cache disposition;
- stable tool invocation IDs;
- response size/schema validation;
- taint metadata for external content;
- privacy-safe trace;
- fake connectors in CI.

## 1.6 Cancellation propagation

### Objective

A task cancellation must prevent every future model/tool/specialist call and signal current cancellable work.

### Deliverables

- durable task cancellation state;
- in-process cancellation token;
- model/tool adapter cancellation where supported;
- child/dependent invocation enumeration;
- no new reservations after cancellation;
- idempotent cancel API;
- race-condition tests.

## 1.7 Context compiler and compaction

### Objective

Build small deterministic specialist context packets instead of passing all conversation and memory.

### Context packet

```text
task contract
selected specialist policy
active project/goal summary
relevant decisions
bounded evidence
approved tool schemas
remaining budget
required output schema
```

### Compaction invariants

Never compact away:

- task/invocation IDs;
- policy version;
- approvals;
- budgets;
- unresolved decisions;
- evidence identity/citations;
- execution and verification state.

## 1.8 End-to-end trace

### Objective

Correlate task, routing, specialist, model, tools, evidence, result, delivery and replay without storing private raw content by default.

### Deliverables

- durable trace metadata or event references;
- per-step timing and cost;
- cache/replay status;
- typed failure reason;
- no prompt, raw tool arguments/results, secrets, raw email, notification, audio or Accessibility tree;
- trace query by task and invocation.

## 1.9 Explicit live-provider staging test

### Objective

Verify one real AvalAI path under a hard budget without introducing live cost into ordinary CI.

### Rules

- manually triggered;
- pinned provider/model/pricing policy;
- one stable invocation ID;
- maximum cost specified before call;
- no automatic retry after transport uncertainty;
- result stored and replayed;
- credentials only on Core/staging secret store;
- staging report records actual usage and cost.

## 1.10 Complete GitHub read workflow

### User command

```text
وضعیت پروژه سیمرغ و PRهای اخیر را بررسی کن
```

### Required path

```text
TaskEnvelope
→ deterministic github.read routing
→ durable specialist invocation
→ governed GitHub read tools
→ repository/PR/CI structured evidence
→ Persian report artifact
→ durable result and cost
→ exact replay with zero duplicate connector/model calls
```

### Definition of Done

- response cites repository artifacts/evidence;
- current CI/PR facts are fetched, not guessed from memory;
- result is Persian and structured;
- replay survives restart;
- changed freshness requirement can force an intentional new read;
- connector/model/tool counts and cost are visible.

# Phase 2 — Native Skill runtime

## 2.1 AgentSkills parser

Validate `SKILL.md` name, description, compatibility, metadata, allowed-tools advisory field and support-file containment.

## 2.2 Skill index and progressive disclosure

- Level 0 metadata index;
- Level 1 Simorgh manifest;
- Level 2 full instructions;
- Level 3 on-demand references/scripts/assets;
- token/byte limits at every level.

## 2.3 Skill policy and scopes

Scopes:

```text
System
User
Workspace
Node
Temporary
```

Location never grants permission.

## 2.4 Learn Routine and Skill Proposal

Extract verified procedure, prerequisites, tools, failures and verification from eligible experience; create a proposal only.

## 2.5 Lint, sandbox, approval and activation

Lifecycle:

```text
draft → proposed → linted → sandbox_tested → pending_approval
→ active → deprecated/revoked
```

## 2.6 Targeted Skill Patch and rollback

Patches bind to base version/hash and include evidence and regression fixtures.

# Phase 3 — Memory and session search

## 3.1 Typed User Profile

Stable, bounded, versioned, user-editable, provenance-aware.

## 3.2 Environment Memory

Non-secret device/runtime/path/tool facts with expiry where needed.

## 3.3 Project and workspace memory

Goals, architecture, decisions, milestones, risks and privacy policy.

## 3.4 Episodic/session storage

SQLite messages, tool invocations, artifacts, task links and FTS indexes.

## 3.5 Hybrid retrieval

FTS + embedding + workspace/time/privacy filters + optional reranking.

## 3.6 Memory candidate review

No inferred fact becomes authoritative without promotion policy.

## 3.7 Memory flush before compaction

Durably save task state, decisions, artifacts, candidates and approvals before summarization.

## 3.8 Edit/delete/export UI

The user can inspect source, validity, authority and remove or correct memory.

# Phase 4 — Personal Work Graph and scheduled missions

## 4.1 Work Graph entities

Goal, Project, Product, Repository, Campaign, Contact, Decision, Task, Dependency, Evidence, Artifact, Routine and Checkpoint.

## 4.2 Bounded task DAG

Cycle, depth, node, parallelism and budget limits.

## 4.3 Event-to-task updates

Only relevant structured deltas create or update tasks; unchanged events cost zero model calls.

## 4.4 ScheduledMission

Pinned/policy-controlled provider/model, tools, permissions, delivery and failure behavior.

## 4.5 Durable run ledger

```text
claimed → running → completed/failed/cancelled/unknown
```

## 4.6 No-agent jobs

Scripts/rules for deterministic alerts, health checks and data collection.

## 4.7 Daily Cockpit

Calendar, notifications, GitHub/CI, project blockers, sales follow-ups, SEO anomalies, deadlines, usage/cost and three evidence-backed priorities.

# Phase 5 — Gateway and channels

## 5.1 Role-based typed WebSocket

Roles: operator, Android Node, worker Node, channel adapter and UI client.

## 5.2 Cryptographic device identity and pairing

Signed challenge, device token, capability-upgrade approval, suspension and revocation.

## 5.3 Telegram first

Inbound normalization, owner authentication, taint metadata, typed task event, approved delivery and receipt.

## 5.4 Deterministic bindings

Channel/account/peer selects workspace, mode and input policy; specialist routing remains separate.

## 5.5 Cross-channel continuation

Resume by durable task/workspace identity, never by blindly merging transcripts.

## 5.6 Doctor and Dashboard

Health, pairing, capabilities, clocks, model/prices, connectors, Skills, queues, missions, privacy, cost, evidence and cancellation.

# Phase 6 — Persian Voice

Prerequisite: Phase 1 runtime.

## 6.1 Local wake engine abstraction

## 6.2 VAD and bounded pre-roll

## 6.3 Persian ASR cascade

## 6.4 N-best and context vocabulary

## 6.5 Mixed Persian/English normalization

## 6.6 Sensitive ambiguity confirmation

## 6.7 Barge-in and immediate cancellation

## 6.8 Persian TTS and pronunciation dictionary

## 6.9 Assistant-role and foreground fallback capabilities

## 6.10 Physical Galaxy A53 benchmark

The existing PR #35 remains Draft until it is rebased onto the durable runtime.

# Phase 7 — Android operator

Every operation is a separate trust boundary and PR:

1. deterministic fixture app;
2. physical `open_app` validation;
3. `click_node`;
4. `set_text` with secret-field policy;
5. `scroll_node`;
6. Notification actions;
7. limited global actions;
8. screenshot/visual grounding fallback;
9. verified multi-step workflows;
10. app-specific reviewed Skills.

# Phase 8 — Delegation

Prerequisites: durable tasks/invocations, cancellation, budget, memory and governed tools.

Initial constraints:

```text
fan-out 2
depth 1
read-only
fresh context
capability subset
pre-reserved budget
```

# Phase 9 — Self-improvement

1. post-task Learning Review;
2. Memory candidate;
3. Skill candidate;
4. targeted Skill Patch;
5. evaluation fixture generation;
6. review queue;
7. cheap/local review model;
8. regression tests;
9. rollback;
10. learning quality and cost metrics.

# Global release gates

Every merged increment must prove:

- typed contracts and strict validation;
- deterministic cost-free path where applicable;
- pre-call cost reservation for external work;
- stable identity and idempotent replay;
- explicit cancellation/deadline behavior;
- no permission widening from models, Skills, MCP or Nodes;
- no raw natural language at executor boundaries;
- authoritative result evidence;
- no secret/private raw content in traces;
- crash/restart semantics;
- full Core and Android CI;
- operational documentation;
- honest statement of what remains process-local, untested or not physically validated.
