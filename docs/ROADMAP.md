# Engineering Roadmap

The roadmap is ordered by architectural risk, not by the number of attractive features. Android operation is the highest-risk and highest-value capability, so it is validated before broad connector expansion.

## Phase 0 — Engineering foundation

### Goal

Create a testable core whose contracts remain valid as models, mobile implementations, and service providers evolve.

### Deliverables

- repository conventions and CI;
- versioned action, observation, and result contracts;
- FastAPI service skeleton;
- AvalAI provider adapter;
- provider capability registry design;
- structured logging and correlation IDs;
- persistence schema proposal;
- prompt/version registry proposal;
- Persian evaluation dataset format;
- architecture, product scope, Android design, ADRs, and research baseline.

### Exit criteria

- core package installs on Python 3.12;
- lint, strict type checking, and tests pass;
- model smoke test works with an AvalAI API key;
- an `ActionPlan` can be serialized and validated;
- CI protects new pull requests.

## Phase 1 — Android vertical slice

### Goal

Execute and verify one real Android task from a Persian command.

### Work packages

#### 1. Android shell

- Kotlin/Compose application;
- device pairing;
- persistent WebSocket transport;
- capability handshake;
- command queue and reconnect behavior;
- diagnostics screen.

#### 2. Observation service

- foreground package and window metadata;
- accessibility service;
- normalized UI tree;
- optional screen capture;
- local trace recorder;
- inspector UI for development.

#### 3. Deterministic executor

- app discovery and launch;
- node lookup;
- tap and set-text operations;
- back/home navigation;
- waits and timeouts;
- post-condition evaluator.

#### 4. Persian planner

- command normalization;
- model-based structured planning through AvalAI;
- JSON-schema validation;
- bounded repair of invalid model output;
- planner evaluation cases.

#### 5. End-to-end scenario

Initial scenario:

> «اسلک را باز کن و قسمت Later را نشان بده.»

The exact target application may change if Slack is unavailable on the test device, but the scenario must include app launch, at least one in-app interaction, and verified completion.

### Exit criteria

- at least 30 recorded end-to-end Persian commands;
- app-open success rate above 95% on the primary test device;
- deterministic UI-action success above 90% for the selected app workflow;
- no action reported as successful without post-state evidence;
- every run is replayable from stored observations and action records.

## Phase 2 — Vision fallback and application skills

### Goal

Operate interfaces whose controls are incomplete or absent in the accessibility tree.

### Deliverables

- MediaProjection capture session;
- AvalAI vision-capable model adapter;
- structured visual grounding schema;
- gesture executor;
- confidence and ambiguity handling;
- reusable skill format;
- app-version matching;
- fixture replay tests;
- loop detection and recovery.

### Exit criteria

- at least three applications with tested skills;
- measured comparison of node-only, vision-only, and hybrid execution;
- visual grounding accuracy and task completion metrics recorded;
- layout-change recovery test implemented.

## Phase 3 — Builder OS

### Goal

Turn Simorgh into a serious development and product-building agent.

### Deliverables

- GitHub connector and repository workspace model;
- issue/branch/commit/PR workflow;
- sandboxed code execution;
- repository indexing and code search;
- test and CI diagnosis;
- deployment adapters;
- technical documentation generator;
- architecture and code-review agents;
- release workflow and changelog generation.

### Exit criteria

- Simorgh can implement a bounded issue in a test repository through a draft PR;
- tests and review evidence are attached to the mission;
- failed CI is diagnosed using logs rather than guessed from status alone;
- deployment operations remain separated from code-generation reasoning.

## Phase 4 — Personal work OS

### Goal

Coordinate daily information and commitments.

### Initial connectors

- Gmail;
- Google Calendar;
- Google Drive and Docs;
- Slack;
- Notion;
- GitHub notifications;
- Telegram.

### Capabilities

- morning briefing;
- unified search;
- inbox triage;
- draft responses;
- meeting preparation;
- task and commitment extraction;
- project status summaries;
- recurring reports.

## Phase 5 — SEO and Growth OS

### Goal

Make Simorgh an evidence-driven SEO, analytics, and growth specialist.

### Connectors and datasets

- Google Search Console;
- Google Analytics Data API;
- site crawler;
- sitemap and robots analysis;
- PageSpeed and performance data;
- keyword and SERP research providers;
- Google Business Profile;
- later: Google Ads and other advertising systems.

### Capabilities

- technical audit;
- indexation and canonical diagnosis;
- query/page/opportunity analysis;
- content-gap research;
- content briefs;
- internal-link proposals;
- experiment planning;
- funnel and conversion reporting;
- anomaly detection;
- recurring executive growth report.

## Phase 6 — Marketing, content, and sales OS

### Goal

Support the full path from product positioning to revenue.

### Capabilities

- market and competitor research;
- ICP and segmentation;
- positioning and offers;
- campaign planning;
- channel-specific content;
- social publishing workflows;
- creative briefs;
- email sequences;
- lead capture, enrichment, scoring, and follow-up;
- proposal generation;
- pipeline reporting;
- customer feedback synthesis.

## Phase 7 — Durable proactive missions

### Goal

Move from individual commands to persistent objectives.

### Deliverables

- durable workflow runtime;
- event subscriptions and scheduled wakeups;
- mission budgets and limits;
- checkpointed multi-day work;
- proactive anomaly and opportunity detection;
- learned routine proposals;
- specialist-agent parallelism;
- verifier and critic loops;
- cost and performance optimization.

## Cross-cutting workstreams

These continue throughout all phases:

- Persian language and voice evaluation;
- observability and cost attribution;
- memory correctness and provenance;
- connector contract tests;
- recorded Android regression fixtures;
- documentation and ADR maintenance;
- performance and reliability engineering.
