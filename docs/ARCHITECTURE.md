# System Architecture

## 1. Architectural objective

Simorgh must coordinate probabilistic model reasoning with deterministic device and service execution. The architecture therefore separates **reasoning**, **planning**, **execution**, **verification**, and **memory** into explicit components.

A model is never treated as the source of truth for whether an operation succeeded. External state is observed after execution and compared with typed post-conditions.

## 2. System context

```text
Owner
  |
  +-- Android application
  +-- Web control center
  +-- Voice interface
  +-- Messaging surfaces
          |
          v
+-----------------------------+
| Simorgh Core                |
|                             |
| API Gateway                 |
| Session / Context Manager   |
| Executive Orchestrator      |
| Specialist Agent Runtime    |
| Model Router                |
| Workflow Engine             |
| Policy / Approval Engine    |
| Memory / Knowledge          |
| Audit / Telemetry           |
+-------------+---------------+
              |
    +---------+----------+----------------+
    |                    |                |
    v                    v                v
AvalAI Gateway     Android Operator   Service Connectors
                                      Google / Slack /
                                      Notion / GitHub /
                                      SEO / Marketing
```

## 3. Primary components

### 3.1 Android application

Responsibilities:

- Persian text and voice interaction;
- foreground and background connection to Simorgh Core;
- device identity and session management;
- rendering plans, progress, evidence, and errors;
- hosting the Android Operator services;
- local event collection and local encrypted state;
- resilient command queue when the network is unavailable.

### 3.2 Executive orchestrator

Responsibilities:

- normalize user intent;
- retrieve relevant context and memory;
- select one or more specialist agents;
- request a structured plan;
- validate plan structure;
- coordinate execution and replanning;
- summarize progress and results to the user.

The orchestrator is not allowed to execute arbitrary code or call raw provider APIs. It operates through registered typed tools.

### 3.3 Specialist agent runtime

Each specialist is a configuration consisting of:

- role and domain instructions;
- allowed tools;
- preferred model capabilities;
- context sources;
- evaluation suite;
- output schema.

Initial specialists are Android Operator, Software Engineering, DevOps, SEO, Growth, Marketing, Sales, Research, Communications, Data Analysis, and Verification.

### 3.4 Model router

The model router owns provider-specific behavior. It exposes provider-independent operations such as:

- text reasoning;
- structured plan generation;
- vision analysis;
- embeddings;
- speech recognition;
- speech synthesis;
- model discovery and capability metadata.

AvalAI is implemented as the first provider adapter using the official OpenAI SDK with a custom base URL. Models are selected by capability policy rather than hard-coded throughout the application.

### 3.5 Action runtime

The action runtime accepts a versioned `ActionPlan`. Each action contains:

- kind;
- target;
- arguments;
- risk classification;
- retry policy;
- idempotency key where applicable;
- one or more post-conditions.

Execution state transitions are explicit:

```text
planned -> running -> succeeded
                   -> failed
                   -> blocked
                   -> cancelled
```

### 3.6 Android Operator

The Android Operator is a device-side executor with four ordered control strategies:

1. Android intent or deep link;
2. deterministic accessibility-node action;
3. reusable application skill;
4. visual grounding and gesture execution.

It produces observations containing package identity, activity/window metadata, accessibility tree, optional screenshot reference, and action evidence.

### 3.7 Connector runtime

Connectors expose external services through typed operations. Connector implementation order:

1. direct official API client for critical services;
2. MCP adapter when the server is trusted and the contract is adequate;
3. browser automation for unsupported web operations;
4. Android application operation as a final fallback.

A connector must define capability metadata, input schema, output schema, retry semantics, rate-limit behavior, and verification strategy.

### 3.8 Workflow engine

Short interactive tasks execute in the request/session runtime. Long-running missions use persisted workflow state with:

- checkpoints;
- retries with backoff;
- event waits;
- scheduled wakeups;
- idempotent steps;
- human-input waits;
- cancellation;
- compensation or rollback steps.

The exact durable-workflow implementation is deferred until after the Android vertical slice. Its public contracts are defined before selection to avoid runtime lock-in.

### 3.9 Memory system

Memory is split into separate stores:

- working context;
- episodic timeline;
- semantic facts;
- procedural skills;
- commitments;
- project/person relationship graph;
- source documents and embeddings.

Every persistent memory item carries provenance, confidence, sensitivity, timestamps, and retention metadata.

### 3.10 Observability

Every mission receives a correlation ID. The trace includes:

- user input;
- normalized intent;
- context retrieval;
- model and provider selection;
- prompts by hash/version;
- token and monetary usage;
- generated plans;
- tool calls;
- observations;
- verification decisions;
- retries and failures;
- final outcome.

OpenTelemetry-compatible traces and structured logs are the target representation.

## 4. Android operation sequence

```text
Command
  -> Intent normalization
  -> Planner produces ActionPlan
  -> Plan validation
  -> Send action to paired Android device
  -> Capture pre-observation
  -> Select control strategy
  -> Execute action
  -> Capture post-observation
  -> Evaluate post-condition
  -> Success, retry, replan, or stop
  -> Persist complete trace
```

## 5. Data boundaries

- Mobile application never contains the AvalAI API key.
- Model calls originate from Simorgh Core.
- Raw screenshots are stored only when required by an active trace or evaluation case.
- Credentials are referenced by opaque IDs and retrieved by connector workers.
- Agents receive only tool schemas and scoped context, not raw secret material.

## 6. Initial technology baseline

- Android: Kotlin, Jetpack Compose, AccessibilityService, MediaProjection, WorkManager, Room/SQLCipher.
- Core API: Python 3.12, FastAPI, Pydantic.
- Model access: provider interface with AvalAI adapter.
- Persistence: PostgreSQL; pgvector only where semantic retrieval is justified.
- Eventing: initially in-process interfaces; later Redis Streams or NATS after workload evidence.
- Testing: pytest, Android instrumentation tests, recorded UI fixtures, end-to-end device tests.
- Quality: Ruff, mypy, GitHub Actions.

## 7. Architectural constraints

- No business domain may call a model provider directly.
- No agent may bypass typed tools.
- No Android gesture may be considered successful without a post-observation.
- Provider-specific model names may appear only in configuration and capability registries.
- Application-specific Android knowledge must live in skills, not in the generic executor.
- Documentation changes are required when public contracts or architectural boundaries change.
