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
Phase 1.2 Durable Invocation Store       COMPLETE — PR #39
Phase 1.3 Specialist Execution           COMPLETE — PR #44
Phase 1.4 Typed Results and Artifacts    COMPLETE — PR #48
Phase 1.5 Governed GitHub Read Tools     COMPLETE — PR #52
Phase 1.6 Cancellation Propagation       COMPLETE — PR #54
Phase 1.7 Context Compiler               COMPLETE — PR #56
Phase 1.8 End-to-End Trace               VALIDATING — PR #60
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

## 1.2 Durable invocation store — COMPLETE

Merged through PR #39 at `49026c89a2a0ba05b179665a993bb66385d880f4`.

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

## 1.3 Specialist execution interface — COMPLETE

Merged through PR #44 at `2bc113a29960a1935db3f91c27cb6863f0ac35b5`. Issue #40 completed; ADR 0016 accepted.

Delivered in PR #44:

- immutable request/result contracts derived from durable route and compiled policy;
- concrete `SpecialistPlanPayload`; arbitrary final dictionaries and raw model text rejected;
- stable context-bundle and cancellation-owner identities;
- explicit capability subset and task/policy budget intersection;
- exact-version implementation registry and deterministic zero-cost proposal executor;
- durable `InvocationStore(kind=specialist)` execution and SQLite restart replay;
- absolute and monotonic deadline checks before and after executor entry;
- cancellation, expiry, changed-context conflict, failure sanitization and result terminalization;
- privacy-safe process-local specialist start/completion/failure/replay traces;
- routed-task adapter with widened/exhausted budget rejection;
- internal zero-external execution control plane with active cancellation and duplicate suppression;
- no public execution endpoint, connector, MCP, model, mutation or Android side effect.

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
- deterministic zero-external proposal implementation;
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
- durable invocation claimed before specialist entry;
- no external reservation for the zero-external fixture;
- monotonic elapsed budget enforced before and after execution;
- completed specialist replay;
- interrupted specialist recovery to unknown;
- cancellation before execution;
- output-contract failure;
- no private context leakage to traces.

## 1.4 Typed result and artifact model — COMPLETE

Merged through PR #48 at `98d56689df4442541e30c77451ab56550e473479`. Issue #46 completed; ADR 0017 accepted. Exact candidate `6bf234e15956203a3efb4f8c1b8fd8e7cb92cd8e` passed CI run `30216281897` with 317 Core tests and full Android build/JVM/lint/APK gates.

### Objective

Separate durable structured results and evidence from user-facing natural-language presentation.

### Delivered in PR #48

- exact-version result registry for `simorgh.typed-plan.v1`, `simorgh.specialist-plan-result`, schema `1.0`;
- immutable `AuthoritativeSpecialistResult` tied to request, invocation, producer, output contract and direct usage identity;
- canonical result ID and SHA-256 independent of replay disposition and presentation;
- bounded artifact metadata with hash, media type, byte size, producer, storage disposition, privacy and retention;
- bounded evidence metadata with source/tool/connector identity, freshness, cache disposition, taint, citation and artifact linkage;
- explicit uncertainty, unresolved risks and verification requirements;
- conservative privacy and retention composition across linked references;
- strict in-memory and SQLite WAL result stores with process ownership, schema/integrity checks and immutable one-result-per-invocation replay;
- cross-authority terminalization against the completed Phase 1.3 invocation payload and committed usage;
- deterministic Persian renderer outside authority fields;
- privacy-safe result commit/replay/failure traces;
- dedicated Core lifespan store path and startup unwind;
- fake/local restart, conflict, corruption, privacy and presentation tests.

### Merge gate satisfied

- no live connector payload, arbitrary model text or presentation text admitted;
- completed replay added no specialist/model/tool/connector call or new usage charge;
- artifact bytes remained outside this metadata authority and are tracked separately in issue #49;
- ADR 0017 and operational/validation documentation synchronized;
- zero unresolved review threads;
- exact candidate passed Core Ruff, strict MyPy and 317 tests;
- exact candidate passed Android build, JVM tests, lint and APK;
- merged scope remained limited to Phase 1.4.

### Explicit non-goals

- no public result endpoint;
- no production artifact-byte storage;
- no live provider, GitHub connector, MCP, mutation executor, Voice, Notification, Memory or new Android effect.

## 1.5 Governed read-only tool execution — COMPLETE

Merged through PR #52 at `7fef6a5262de1e84be89c9afc30c25053945a4ac`. Issue #51 completed; ADR 0018 accepted. The validated implementation head `98f0cc9004e56e76eb9ed1b683099e921ba52d1c` passed CI run `30223753959` with 340 Core tests and full Android build/JVM/lint/APK gates.

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

## 1.6 Cancellation propagation — COMPLETE

Merged through PR #54 at `8fd7cb31275d037cb50a4da0ad86c7871f1be13f`. Issue #53 completed; ADR 0019 accepted. The validated implementation head `930c8bb679e415efbf2f8b412074b9875e8ca3b7` passed CI run `30280106847` with 360 Core tests and full Android build/JVM/lint/APK gates.

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

## 1.7 Context compiler and compaction — COMPLETE

Merged through PR #56 at `dab5333140da2d9cf9b982a57ede1a2d08397cf1`. Issue #55 completed; ADR 0020 accepted. Exact-head validation passed Ruff, strict MyPy, 404 Core tests and full Android build/JVM/lint/APK gates.

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


## 1.8 Durable correlated end-to-end trace — VALIDATING

Implementation is active in Draft PR #60 for issue #57.

### Objective

Reconstruct one durable, ordered, privacy-safe audit projection across task, routing, budget, context, model/tool/specialist invocations, authoritative result, replay, cancellation and uncertainty. Trace remains projection only and never grants execution authority.

### Delivered boundary

- strict typed event/detail/envelope contracts and deterministic IDs/hashes;
- immutable in-memory and SQLite WAL authorities with transactional sequence, exact replay, corruption/schema/process-lock failure semantics;
- direct producer projection after durable task/invocation/context/result commits;
- deterministic startup reconciliation with zero external calls or new usage;
- classifier and specialist-owned model/tool child correlation from exact retained identities;
- typed cancellation settlement and conservative unknown-side-effect handling;
- typed terminal supersession/resolution without rewriting historical events;
- whole-trace terminal retention with active routed-request protection and pre-delete recheck;
- independent path, lifespan ownership, backup/restore and incident procedures;
- deterministic runtime acceptance for budgeted classifier plus governed GitHub read;
- online-backup, standalone restore and corruption fail-closed acceptance.

### Final merge gate

- exact PR Head passes Core installation, Ruff, strict MyPy and all tests;
- the same Head passes Android build, JVM tests, lint and Debug APK upload;
- final validation record pins exact Head, run, test count and artifact digests;
- no temporary workflow/runtime database or unresolved review action remains;
- scope remains Phase 1.8 only.
