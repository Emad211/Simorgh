# Simorgh master architecture and development directive

- Status: Authoritative
- Effective date: 2026-07-25
- Authority: Direct user instruction
- Original source SHA-256: `c89fdecc73b4b09cd710fc35671fd16efd7ca3b5b73b27e616bebfe1e840919f`
- Applies to: architecture, roadmap ordering, trust boundaries, implementation, review, testing, release and future adapters

## 1. Mission

Simorgh must become a permanent, Persian-first, multimodal and reliable personal colleague for one developer/founder.

It is not a general chatbot, a thin model wrapper, a Hermes fork or an OpenClaw clone.

The product promise is:

> Simorgh is the most reliable Persian personal colleague for performing real work on Android and the user's work services.

The target domains are:

- natural and precise Persian interaction;
- evidence-verified Android control;
- project management and software development;
- research and evidence synthesis;
- GitHub work;
- SEO, marketing and sales;
- controllable personal memory;
- repeatable workflow learning;
- predictable cost;
- approval-bound sensitive operations;
- crash-safe long-running execution;
- a persistent daily user experience.

Feature count is not the objective. Correctness, authority, cost, evidence and daily usefulness are the objective.

## 2. Native authority is not delegated

Hermes Agent and OpenClaw are sources of patterns and interoperability, not Simorgh's runtime authority, policy authority or storage authority.

Simorgh remains the sole native authority for:

- `TaskEnvelope` and task identity;
- invocation identity;
- specialist selection;
- budget and cost accounting;
- permissions and approvals;
- task state;
- Personal Work Graph state;
- Android operations;
- execution state;
- authoritative verification;
- audit and privacy boundaries;
- credential policy;
- memory-promotion policy.

The architectural relationship is:

```text
Hermes
  procedural learning, progressive skills, delegation and worker-runtime patterns

OpenClaw
  long-lived Gateway, Channels, Nodes, pairing, Voice and daily UX patterns

Simorgh
  final authority for Policy, Budget, Memory, Execution and Verification
```

An external adapter may receive only a typed task, an explicit capability subset, a pre-reserved budget, a deadline and an output contract.

No external adapter may:

- create or expand budget;
- activate a discovered tool automatically;
- widen permissions;
- change task or invocation identity;
- perform a side effect outside a Simorgh typed executor;
- claim success without a Simorgh verifier;
- write authoritative memory without Simorgh promotion policy.

## 3. Patterns adopted from Hermes Agent

The following patterns are approved for native reimplementation or optional adapters:

- AgentSkills-compatible `SKILL.md` procedural knowledge;
- progressive disclosure of skill metadata, instructions and references;
- controlled Learn Routine generation from successful verified work;
- targeted Skill Patch rather than blind full rewrites;
- bounded curated always-present memory;
- session/episode search separate from memory;
- post-task learning review that creates candidates only;
- fresh-context delegated workers;
- capability inheritance as a strict subset;
- bounded fan-out and spawn depth;
- per-branch cost and cancellation visibility;
- scheduled fresh-session missions;
- no-agent scheduled jobs for deterministic work;
- model-provider and worker-backend abstractions.

These patterns must be tightened in Simorgh:

- a learned Skill is always a proposal first;
- a Skill proposal passes static lint, policy lint, sandbox tests and review;
- child agents cannot write global memory or access sensitive executors;
- child budgets are reserved before spawn;
- child results are typed and independently validated;
- interrupted or uncertain execution is never declared successful;
- procedural learning never becomes permission.

## 4. Patterns adopted from OpenClaw

The following patterns are approved for native reimplementation or optional interoperability:

- one long-lived local-first Gateway;
- typed WebSocket messages and server-push events;
- explicit connection roles;
- device identity and pairing;
- capability-surface upgrade approval;
- Nodes as peripherals rather than authorities;
- capability and command advertisement;
- multi-channel input behind one Gateway;
- deterministic channel binding to workspace and input policy;
- workspace isolation;
- scoped System, User, Workspace, Node and Temporary Skills;
- quarantined Node-hosted capability proposals;
- exact-plan approval bound to a canonical plan hash;
- Voice/Talk surfaces and barge-in UX;
- onboarding, Doctor and health diagnostics;
- structured live cards before a general-purpose Canvas.

These patterns must be tightened in Simorgh:

- the Gateway transports and validates; it does not own agent reasoning;
- Node capability advertisement means availability, never permission;
- Channel input remains untrusted even when sender identity is approved;
- Android Nodes observe, execute approved typed commands and return evidence;
- approval is bound to exact command, arguments, target, content and deadline;
- changed capability or plan invalidates approval;
- external Skill/Plugin/MCP discovery enters quarantine;
- host execution is sandboxed by default.

## 5. Final integrated architecture

```text
User surfaces
  Android | Voice | Telegram | Web | Structured cards
        ↓
Simorgh Gateway
  Auth | Pairing | Channels | Nodes | Events | Presence | Delivery | Health
        ↓
Typed Task Edge
  Identity | Locale | Risk | Freshness | Outcome | Deadline | Budget | Sources
        ↓
Specialist Router
  Explicit type → deterministic rules → at most one bounded classifier
        ↓
Context, Memory and Personal Work Graph
  Profile | Environment | Projects | Episodes | Evidence | Skills | Tasks
        ↓
Specialist Agent Runtime
  Read | Plan | Research | Delegate | Compose | Progressive Skills
        ↓
Policy, Budget and Approval
  Tool/connector allowlists | Plan hash | Credentials | Cost reservation
        ↓
Typed Executors
  Android | GitHub | Gmail | Calendar | Documents
        ↓
Authoritative Verifiers
  API state | Android evidence | CI | receipt | current object identity
        ↓
Trace, Learning and Evaluation
  Audit | Cost | Skill proposals | Memory candidates | Regression fixtures
```

## 6. Memory architecture

Memory is separated into distinct authorities:

1. User Profile — stable user facts and preferences.
2. Environment Memory — non-secret devices, runtimes, paths and tool facts.
3. Project/Workspace Memory — goals, architecture, constraints and decisions.
4. Episodic Memory — task history, evidence, corrections and outcomes.
5. Personal Work Graph — goals, tasks, dependencies, commitments and checkpoints.
6. Procedural Memory — reviewed Skills and workflows.
7. Knowledge/Evidence — claims with source, time, confidence and contradictions.
8. Daily Notes — reviewable chronological summaries with Markdown export.

Rules:

- raw conversations are not automatically permanent memory;
- raw audio, complete notifications and Accessibility trees are not default memory;
- every promoted fact has provenance, scope, confidence, validity and deletion path;
- secrets are references to a secret store, never memory values;
- session search retrieves old detail on demand;
- memory cannot replace current permission, capability, freshness or evidence;
- action-sensitive facts record authority, expiry, safe-to-act constraints and hashes;
- even action-sensitive memory does not replace executor approval.

## 7. Skills and procedural learning

The native Skill Registry must be versioned and AgentSkills-compatible while adding Simorgh policy metadata.

Progressive loading levels:

```text
Level 0 — Skill index
  name, description, version, risk, specialist and requirements

Level 1 — Skill manifest
  triggers, tools, constraints, output and verification contracts

Level 2 — Full SKILL.md
  procedure, pitfalls, examples and verification

Level 3 — On-demand references
  schemas, fixtures, templates, scripts and supporting files
```

Skill lifecycle:

```text
draft
proposed
lint_failed
sandbox_tested
pending_approval
approved
active
deprecated
revoked
```

No generated Skill becomes active directly.

Learning Review output is limited to:

```text
no_learning
memory_candidate
skill_candidate
skill_patch_candidate
environment_fact_candidate
evaluation_fixture_candidate
```

## 8. Delegation

Delegated workers start with fresh context and receive one explicit `ContextBundle`.

Required delegation fields include:

- stable delegation and parent task IDs;
- goal;
- context bundle identity;
- specialist identity;
- capability subset;
- pre-reserved budget;
- deadline;
- output contract;
- spawn depth.

Rules:

- child capabilities are a subset of parent capabilities;
- global-memory write is disabled;
- sensitive executors are unavailable;
- fan-out and depth are bounded;
- nested orchestration is disabled by default;
- cancellation propagates by ownership;
- only typed summaries enter parent context;
- full transcripts are audit artifacts, not prompt context;
- uncertain completion after interruption is fail-closed.

Initial delegation limits after prerequisite phases:

```text
fan-out = 2
depth = 1
risk = read-only
```

## 9. Scheduled missions

Scheduling uses typed `ScheduledMission`, never an unbounded cron prompt.

Every mission pins or policy-controls:

- timezone;
- typed task template;
- specialist;
- provider/model policy;
- maximum cost;
- connectors and tools;
- delivery surface;
- failure and schema-change behavior.

Rules:

- scheduled jobs cannot create scheduled jobs;
- deterministic no-agent mode is preferred where sufficient;
- model, price, Skill, schema or permission changes pause or quarantine the mission;
- sensitive missions do not run without user presence;
- execution and delivery are separate;
- crash uncertainty is recorded as `unknown` and not automatically retried unless idempotency is proven.

Run states:

```text
claimed
running
completed
failed
cancelled
unknown
```

## 10. Security defaults

Simorgh does not copy host-first or YOLO defaults.

Defaults:

```text
Read-only API connectors
  narrow credentials on Core

Shell, code and browser
  sandbox by default

Android mutations
  native typed executor only

Send, publish, delete, financial and production operations
  exact-plan approval and dedicated executor
```

A Disposable Lab Mode may exist only with ephemeral storage, no production secrets, restricted network, no real connectors and no Android executor.

Untrusted data sources include web pages, email, notifications, channels, GitHub issues, downloaded files, MCP output, screen text, OCR and external tool descriptions.

Untrusted data may influence reasoning but may not:

- grant permissions;
- define tools;
- activate Skills;
- write authoritative memory;
- modify policy;
- authorize side effects.

Every sensitive approval is bound to a canonical plan hash. Changes to command, arguments, target, account, file, working directory, recipient, amount, body, deadline or permission scope invalidate it.

Hardline deny rules cannot be disabled through chat.

## 11. Required implementation order

The implementation order is authoritative.

### Phase 1 — Complete the native runtime

1. Durable task store.
2. Durable invocation store.
3. Specialist execution interface.
4. Typed specialist result.
5. Governed read-only tool execution.
6. Cancellation propagation.
7. Context compilation and compaction.
8. End-to-end trace.
9. Explicitly budgeted live-provider staging test.
10. Complete GitHub read workflow.

Definition of Done:

```text
«وضعیت پروژه سیمرغ و PRهای اخیر را بررسی کن»

TaskEnvelope
→ github.read
→ GitHub connector
→ structured evidence
→ Persian report
→ persisted task/result/cost
→ exact replay without duplicate calls
```

### Phase 2 — Skill runtime

AgentSkills parser, index, progressive disclosure, policy allowlists, proposals, lint, sandbox tests, approval, versioning and rollback.

### Phase 3 — Memory and session search

Typed profile/environment/project memory, SQLite/FTS session storage, hybrid retrieval, memory-candidate review, compaction flush, privacy controls and user edit/delete/export UI.

### Phase 4 — Scheduled missions and Personal Work Graph

Work Graph schema, bounded task DAG, event-to-task updates, scheduled missions, pinned model policy, run ledger, no-agent jobs, delivery router and Daily Cockpit.

### Phase 5 — Gateway and channels

Role-based WebSocket protocol, cryptographic identity, pairing lifecycle, Telegram, deterministic bindings, delivery receipts, cross-channel continuation, taint metadata, rate limits and diagnostics.

### Phase 6 — Voice

Local wake word, VAD, Persian ASR, N-best, mixed-language normalization, barge-in, cancellation, TTS, sensitive transcript confirmation and physical Android testing.

### Phase 7 — Android operator

Fixture app, physical A53 validation, `click_node`, `set_text`, `scroll_node`, Notification actions, limited global actions, visual fallback and verified multi-step workflows.

Every Android operation has its own executor, verifier, capability and PR.

### Phase 8 — Delegation

Only after durable tasks, budgets, memory, tools and cancellation are stable.

### Phase 9 — Self-improvement

Learning Review, Memory/Skill proposals, targeted patches, evaluation fixtures, approval queue, cheap/local review model, regression tests, rollback and metrics.

## 12. Work currently parked

The Persian Voice/Wake-word work in PR #35 is preserved as a Draft but must not merge before Phase 1 issue #36 is complete.

Voice will later submit work through the durable execution interface, not bypass it through a routing-only endpoint.

## 13. Features intentionally deferred

Before several real end-to-end workflows are complete, do not build:

- dozens of messaging channels;
- a public Skill marketplace;
- a complex general Canvas;
- unlimited autonomy;
- deep nested multi-agent trees;
- automatic memory dreaming without review;
- a general host-access browser agent;
- arbitrary-code plugins;
- financial execution;
- mass outreach;
- adversarial multi-tenancy;
- a complex distributed cluster;
- automatic execution of discovered MCP tools;
- continuous paid thinking loops.

## 14. Non-negotiable engineering rules

1. Every capability has a typed contract.
2. Schema is not permission.
3. Tool discovery is not authorization.
4. Skill presence is not capability.
5. Memory is not approval.
6. A model cannot create budget.
7. A child cannot widen tools.
8. Raw natural language does not enter an executor.
9. A side effect is not successful without evidence.
10. An uncertain side effect is not automatically repeated after crash.
11. Sensitive operations require exact plan hash and freshness checks.
12. Automatic Memory/Skill changes use a review path.
13. External cost is reserved before invocation.
14. Every connector uses narrow credentials.
15. Every workspace has a privacy boundary.
16. Channels remain untrusted inputs.
17. External MCP and Skills enter quarantine.
18. End-to-end workflow quality outranks feature count.
19. Physical Android evidence is recorded separately from fixtures.
20. One PR must not open more than one major trust boundary.

## 15. Benchmark definition

Success is measured across:

- Persian understanding and mixed Persian/English entities;
- Android stale-state and duplicate-side-effect rejection;
- project/session continuity and correct memory correction;
- deterministic low-cost routing and justified escalation;
- prompt-injection, path, symlink, stale approval and secret-leak resistance;
- transparent UX showing specialist, model, cost, data access, proposed effects, approvals, evidence and cancellation.

## 16. Final definition of excellence

```text
Hermes-quality learning
+ OpenClaw-quality permanent presence
+ Simorgh-native policy and cost control
+ Persian-first interaction
+ evidence-verified Android execution
```

A daily user must be able to issue natural Persian missions, recover accurate project context, use reviewed Skills, route work to narrow affordable specialists, act through services and Android, verify results with evidence, see cost and risk, and remain protected against crashes, duplicate operations, prompt injection and incorrect memory.

## 17. Change control

Any future proposal that changes phase order, native authority, security defaults, approval semantics, cost reservation, durability or evidence requirements must:

1. cite this directive;
2. identify the exact clause being changed;
3. provide evidence and trade-offs;
4. receive explicit user approval;
5. be recorded in a dedicated ADR;
6. preserve a migration and rollback path.
