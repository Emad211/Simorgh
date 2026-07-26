# Simorgh gated implementation master plan

- Status: Active
- Governing directive: [`SIMORGH_MASTER_DIRECTIVE.md`](SIMORGH_MASTER_DIRECTIVE.md)
- Planning rule: one major trust boundary per pull request
- Cost rule: fake/local providers in ordinary CI; live tests are explicit, budgeted and separately triggered
- Android rule: automated fixtures and physical Galaxy A53 evidence are reported separately

## Status legend

```text
COMPLETE    merged to main with exact-head CI evidence
VALIDATING  implementation exists in an open PR; merge gates are not yet complete
QUEUED      required design is known but implementation has not opened
PARKED      work is preserved but blocked by an earlier prerequisite
```

## Execution protocol for every step

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
Operational documentation and ADR
    ↓
Full Core + Android CI
    ↓
Review, exact-head validation and merge
```

A step is not complete because code exists. It is complete only when its failure semantics, recovery behavior, cost behavior, privacy boundary and evidence are testable and documented.

# Current execution position

```text
Phase 0 Governance                       COMPLETE
Phase 1.1 Durable Task Store             COMPLETE — PR #37
Phase 1.2 Durable Invocation Store       VALIDATING — issue #38 / PR #39
Phase 1.3 Specialist Execution           QUEUED
Phase 1.4 Typed Results and Artifacts    QUEUED
Phase 1.5 Governed GitHub Read Tools     QUEUED
Phase 1.6 Cancellation Propagation       QUEUED
Phase 1.7 Context Compiler               QUEUED
Phase 1.8 End-to-End Trace               QUEUED
Phase 1.9 Live Provider Staging          QUEUED
Phase 1.10 Complete GitHub Workflow      QUEUED
Phase 2+                                 BLOCKED by Phase 1
Voice PR #35                             PARKED
```

# Phase 0 — Governance baseline

## 0.1 Adopt the master directive — COMPLETE

Delivered:

- authoritative repository directive;
- byte-exact archived source and SHA-256 regression test;
- native-authority rules;
- implementation order;
- trust-boundary rules;
- change-control procedure.

Gate satisfied:

- later product surfaces cannot bypass native task, budget, policy, execution or verification authorities;
- deferred Voice work remains preserved and parked.

## 0.2 Establish roadmap issues — COMPLETE

Delivered:

- parent Phase 1 issue #36;
- durable invocation issue #38;
- Voice issue #31 and Draft PR #35;
- Notification issue #32;
- MCP issue #33;
- Personal Work Graph issue #34.

# Phase 1 — Complete the native specialist runtime

## 1.1 Durable task store — COMPLETE

Merged through PR #37.

### Objective

Make task identity, routing state, budget snapshot, cancellation, expiry and replay survive Core restart.

### Delivered

- `AgentTaskStore` protocol;
- strict in-memory and SQLite WAL implementations;
- canonical payload hash and indexed-column integrity checks;
- immutable task identity/fingerprint;
- write-ahead `routing` claim;
- restart recovery to `unknown`;
- durable cancellation and expiry;
- storage-failure latch;
- stale-memory rejection after durable failure;
- bounded terminal payload retention;
- startup/shutdown integration;
- recovery, backup and incident documentation;
- full Core and Android CI.

### Remaining known boundary

Task replay protection currently follows retained task payloads. Compact long-lived tombstones are a future retention design.

## 1.2 Durable invocation store — VALIDATING

Issue #38; Draft PR #39.

### Objective

Make model, tool and future specialist invocation identity, reservation uncertainty, terminal state, typed result and exact replay survive restart.

### Architecture

```text
durable task
    ↓
durable pending invocation identity
    ↓
request-budget reservation
    ↓
durable invocation usage reservation
    ↓
provider / structured tool / future specialist
    ↓
durable completed result or terminal uncertainty
```

### Implemented in PR #39

- `InvocationStore` protocol;
- strict in-memory implementation;
- SQLite WAL implementation;
- immutable request/agent/version/operation/input identity;
- model/tool/specialist kind;
- read/proposal/mutation effect class;
- pending/reserved/completed/failed/cancelled/expired/unknown states;
- `unknown_side_effect` for uncertain mutations;
- provider/model and tool/connector identity;
- durable worst-case reservation before external call;
- actual or conservative committed usage;
- typed result payload, SHA-256 and one-megabyte limit;
- exact completed replay after restart;
- no duplicate model/tool call or budget charge on replay;
- pending/reserved restart recovery;
- conservative reserved-usage recovery;
- provider/tool error-message redaction;
- generic validation errors that do not echo payload;
- task-parent usage reconciliation without double count;
- direct ungoverned model endpoint disabled;
- application-lifespan configuration;
- fake-provider and fake-tool restart tests.

### Required final tests

- SQLite round trip and reopen;
- completed model replay with provider call count unchanged;
- completed tool replay with invoker count unchanged;
- replay leaves a fresh budget untouched;
- changed input/target conflict;
- pending recovery to unknown;
- reserved read recovery with conservative usage;
- reserved mutation recovery to unknown-side-effect;
- cancellation and expiry persistence;
- result/usage immutability;
- payload-size rejection without private echo;
- provider/tool exception text absent from records and traces;
- durable-reservation failure prevents external call and releases request budget;
- task/invocation usage reconciliation at startup;
- corruption and schema failure;
- startup unwind;
- full Core and Android CI.

### Merge gate

- ADR 0015 accepted;
- operations documentation complete;
- no unresolved review thread;
- exact PR Head has green Core Ruff, strict MyPy and tests;
- exact PR Head has green Android build, JVM tests, lint and APK;
- ordinary CI makes no live provider, connector or MCP call;
- PR remains limited to invocation durability.

### Explicit non-goals

- no specialist execution;
- no live GitHub connector;
- no automatic or explicit retry API;
- no complete task-to-invocation cancellation orchestration;
- no mutation executor;
- no Voice/Notification/MCP work;
- no distributed multi-process store lease.

## 1.3 Specialist execution interface — QUEUED

### Objective

Execute one selected specialist through a narrow typed runtime without exposing all tools, credentials or provider configuration.

### Contract

```text
SpecialistExecutionRequest
  task and invocation identity
  selected specialist/version
  context bundle identity
  capability subset
  effective budget
  deadline
  output contract

SpecialistExecutionResult
  typed terminal state
  artifact/evidence references
  direct usage
  bounded reason
  verification requirements
```

### Deliverables

- runtime-neutral specialist interface;
- native implementation registry;
- fake/no-op implementation;
- model-backed implementation adapter;
- durable specialist invocation identity;
- in-process cancellation token;
- strict task/specialist/capability intersection;
- no model-selected permissions;
- fresh-context execution option;
- no mutation authority.

### Tests

- one selected owner only;
- wrong specialist version rejected;
- capability widening rejected;
- budget reserved before specialist entry;
- completed specialist replay;
- interrupted specialist recovery to unknown;
- cancellation before execution;
- output-contract failure;
- no private context leakage to traces.

## 1.4 Typed result and artifact model — QUEUED

### Objective

Separate durable structured results and evidence from user-facing natural-language presentation.

### Deliverables

- `SpecialistResult` contract;
- artifact ID, hash, media type, size and producer identity;
- evidence references with source, retrieval time and freshness;
- explicit uncertainty and unresolved risks;
- result schema/version identity;
- bounded inline result and external artifact references;
- Persian renderer outside authority fields;
- immutable completed result;
- privacy classification and retention metadata.

### Gate

No live connector payload or arbitrary model text may be persisted as a final specialist result without passing this contract.

## 1.5 Governed read-only tool execution — QUEUED

### Objective

Let a specialist obtain authoritative current evidence while preserving all policy intersections.

### Enforcement

```text
task allowed_data_sources
∩ specialist connector allowlist
∩ specialist tool allowlist
∩ connector/server policy
∩ workspace privacy policy
∩ remaining budget
```

### First connector

GitHub read-only.

### Deliverables

- connector-neutral read interface;
- GitHub repository, PR, check and file-read projections;
- typed response schemas;
- response size limits;
- freshness and cache disposition;
- untrusted-source taint metadata;
- durable invocation IDs;
- evidence citations;
- fake GitHub connector in ordinary CI;
- optional explicitly triggered live validation.

### Non-goals

- no commit, push, merge, comment, issue mutation or PR creation;
- no raw connector response persisted as a specialist result;
- no dynamically discovered tool permission.

## 1.6 Cancellation propagation — QUEUED

### Objective

A task cancellation must stop every future reservation and signal every owned cancellable invocation.

### Deliverables

- task-to-invocation ownership index;
- durable cancellation request;
- in-process cancellation token;
- provider/tool adapter cancellation where supported;
- pending invocation cancellation;
- reserved invocation uncertainty semantics;
- child/dependent invocation enumeration;
- race-safe idempotent cancel API;
- cancellation audit events.

### Rules

- cancellation never proves a reserved external call did not happen;
- uncertain mutations become `unknown_side_effect`;
- cancellation cannot erase committed cost;
- completed results remain immutable.

## 1.7 Context compiler and compaction — QUEUED

### Objective

Build small deterministic context packets instead of passing entire conversations, memory or tool catalogs.

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

- task and invocation IDs;
- policy and schema versions;
- approvals and plan hashes;
- budgets and committed usage;
- unresolved decisions;
- evidence identity and citations;
- execution and verification state;
- cancellation or uncertainty state.

### Gate

Compaction occurs only after durable state and candidate-memory flush.

## 1.8 End-to-end trace — QUEUED

### Objective

Correlate task, routing, specialist, model, tools, evidence, result, delivery and replay without storing raw private content by default.

### Deliverables

- durable or durably referenced trace events;
- task/invocation correlation;
- per-step timing and cost;
- cache and replay disposition;
- typed failure reason;
- query by task/invocation;
- redaction and retention policy;
- no prompt, raw tool arguments/results, secrets, raw email, notification, audio or Accessibility tree.

## 1.9 Explicit live-provider staging test — QUEUED

### Objective

Verify one real AvalAI path under a hard budget without introducing live cost into ordinary CI.

### Rules

- manually triggered only;
- pinned provider/model and price policy;
- one stable invocation ID;
- maximum cost reserved before call;
- no automatic retry after transport uncertainty;
- typed result stored and replayed;
- credentials only in Core/staging secret storage;
- report includes actual tokens, cost, latency and replay evidence;
- staging data excludes private user content.

## 1.10 Complete GitHub read workflow — QUEUED

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
→ typed Persian report artifact
→ durable result and cost
→ exact replay with zero duplicate connector/model calls
```

### Definition of Done

- current GitHub facts are fetched, not guessed from memory;
- response cites repository artifacts/evidence;
- result is Persian and structured;
- task, specialist, tool and optional model identities are durable;
- replay survives restart;
- changed freshness requirement intentionally creates new read identities;
- connector/model/tool counts and cost are visible;
- cancel and failure semantics are testable;
- fake connector CI is complete;
- one optional live read-only validation is documented.

# Phase 2 — Native Skill runtime

Status: BLOCKED by Phase 1.

## 2.1 AgentSkills parser

Validate `SKILL.md` name, description, compatibility, metadata, advisory allowed-tools field and support-file containment.

## 2.2 Skill index and progressive disclosure

```text
Level 0 — metadata index
Level 1 — Simorgh manifest
Level 2 — full SKILL.md
Level 3 — on-demand references/scripts/assets
```

Each level has token/byte limits. Irrelevant Skills never enter context.

## 2.3 Skill policy and scopes

```text
System
User
Workspace
Node
Temporary
```

Location never grants permission.

## 2.4 Learn Routine and Skill Proposal

Extract only verified procedure, prerequisites, tools, failure modes and verification from eligible experience. Create a proposal, never an active Skill.

## 2.5 Lint, sandbox, approval and activation

```text
draft → proposed → linted → sandbox_tested → pending_approval
→ active → deprecated/revoked
```

## 2.6 Targeted Skill Patch and rollback

Patches bind to base version/hash, evidence tasks and regression fixtures. No blind full rewrite.

# Phase 3 — Memory and session search

Status: BLOCKED by Phase 1 and Skill policy foundations.

## 3.1 Typed User Profile

Stable, bounded, versioned, provenance-aware and user-editable.

## 3.2 Environment Memory

Non-secret device, runtime, path and tool facts with validity windows.

## 3.3 Project and workspace memory

Goals, architecture, constraints, decisions, milestones, risks and privacy policy.

## 3.4 Episodic/session storage

SQLite sessions, messages, invocations, artifacts, task links and FTS indexes.

## 3.5 Hybrid retrieval

FTS + embedding + workspace/time/privacy filters + optional reranking.

## 3.6 Memory candidate review

No inferred fact becomes authoritative without promotion policy and deletion path.

## 3.7 Memory flush before compaction

Durably save task state, decisions, artifacts, candidates and approvals before summarization.

## 3.8 Edit/delete/export UI

The user can inspect source, validity, authority and remove or correct memory.

# Phase 4 — Personal Work Graph and scheduled missions

Status: BLOCKED by durable specialist results and Memory foundations.

## 4.1 Work Graph entities

Goal, Project, Product, Repository, Campaign, Contact, Decision, Task, Dependency, Evidence, Artifact, Routine and Checkpoint.

## 4.2 Bounded task DAG

Cycle, depth, node, parallelism and budget limits.

## 4.3 Event-to-task updates

Only relevant structured deltas create or update tasks. Unchanged events cost zero model calls.

## 4.4 ScheduledMission

Pinned or policy-controlled provider/model, tools, permissions, delivery and failure behavior.

## 4.5 Durable run ledger

```text
claimed → running → completed/failed/cancelled/unknown
```

## 4.6 No-agent jobs

Scripts/rules for deterministic alerts, health checks and data collection.

## 4.7 Daily Cockpit

Calendar, Notifications, GitHub/CI, project blockers, sales follow-ups, SEO anomalies, deadlines, usage/cost and three evidence-backed priorities.

# Phase 5 — Gateway and channels

Status: BLOCKED by durable tasks, invocations, results and Work Graph.

## 5.1 Role-based typed WebSocket

Roles: operator, Android Node, worker Node, channel adapter and UI client.

## 5.2 Cryptographic device identity and pairing

Signed challenge, device token, capability-upgrade approval, suspension and revocation.

## 5.3 Telegram first

Inbound normalization, owner authentication, taint metadata, typed task event, approved delivery and receipt.

## 5.4 Deterministic bindings

Channel/account/peer selects workspace, mode and input policy. Specialist routing remains separate.

## 5.5 Cross-channel continuation

Resume by durable task/workspace identity, never by blindly merging transcripts.

## 5.6 Doctor and Dashboard

Health, pairing, capabilities, clocks, model/prices, connectors, Skills, queues, missions, privacy, cost, evidence and cancellation.

# Phase 6 — Persian Voice

Status: PARKED; PR #35 preserved.

Prerequisite: Phase 1 runtime and cancellation path.

1. local wake engine abstraction;
2. VAD and bounded pre-roll;
3. Persian ASR cascade;
4. N-best and context vocabulary;
5. mixed Persian/English normalization;
6. sensitive ambiguity confirmation;
7. barge-in and immediate cancellation;
8. Persian TTS and pronunciation dictionary;
9. Assistant-role and foreground fallback capabilities;
10. physical Galaxy A53 benchmark.

Voice must submit through the durable task/specialist runtime. It cannot call providers, connectors or Android executors directly.

# Phase 7 — Android operator

Status: BLOCKED; only the separately reviewed `open_app` boundary is active.

Every new operation is a separate trust boundary and PR:

1. deterministic fixture app;
2. physical `open_app` validation;
3. `click_node`;
4. `set_text` with secret-field policy;
5. `scroll_node`;
6. Notification actions;
7. limited global actions;
8. screenshot/visual-grounding fallback;
9. verified multi-step workflows;
10. app-specific reviewed Skills.

# Phase 8 — Delegation

Status: BLOCKED by durable specialist execution, cancellation, budget, memory and governed tools.

Initial constraints:

```text
fan-out = 2
depth = 1
read-only only
fresh context
capability subset
pre-reserved branch budget
typed result
```

Child agents cannot widen tools, write global memory or access sensitive executors.

# Phase 9 — Self-improvement

Status: BLOCKED by Skill and Memory review paths.

1. post-task Learning Review;
2. Memory candidate;
3. Skill candidate;
4. targeted Skill Patch;
5. evaluation-fixture generation;
6. approval queue;
7. cheap/local review model;
8. regression tests;
9. rollback;
10. learning quality and cost metrics.

# Global release gates

Every merged increment must prove:

- typed contracts and strict validation;
- deterministic cost-free path where applicable;
- pre-call durable cost reservation for external work;
- stable identity and idempotent replay;
- explicit cancellation, expiry and crash semantics;
- no permission widening from models, Skills, MCP, Channels or Nodes;
- no raw natural language at executor boundaries;
- authoritative result evidence for side effects;
- no secret/private raw content in traces or failure messages;
- honest storage-encryption and retention boundaries;
- full Core and Android CI;
- ordinary CI uses no live provider or connector;
- operational documentation and ADR;
- honest statement of what remains process-local, untested or not physically validated.
