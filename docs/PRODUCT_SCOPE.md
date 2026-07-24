# Product Scope

## 1. Product definition

Simorgh is a private, Persian-first personal agent operating system for a single owner. Its purpose is to help the owner **create products, write software, operate infrastructure, acquire customers, market, sell, communicate, research, and control Android applications** from one continuous interface.

The system is not defined by a chat UI. It is defined by its ability to convert intent into durable, observable, verified work across devices and services.

## 2. Primary user

The initial and only required user is the repository owner. Multi-tenancy, public distribution, app-store compliance, and general consumer onboarding are not phase-one requirements.

## 3. Product pillars

### 3.1 Android operator

The highest-priority pillar. Simorgh must be able to:

- discover installed applications;
- open an application by package, label, intent, or deep link;
- inspect the current UI using the accessibility tree;
- capture screen state when structural information is insufficient;
- locate controls using deterministic selectors first and vision second;
- tap, long-press, swipe, scroll, type, submit, go back, and return home;
- observe notifications and invoke notification actions;
- build reusable, versioned skills for frequently used applications;
- verify that each action reached its intended post-condition;
- stop and request guidance when confidence is insufficient.

### 3.2 Builder and software-development agent

Simorgh acts as a senior product engineer and development organization:

- product discovery and requirements engineering;
- architecture and technical decision records;
- repository analysis and codebase navigation;
- feature implementation;
- automated tests and quality checks;
- issue, branch, commit, pull-request, and review workflows;
- CI/CD diagnosis;
- deployment, observability, incident analysis, and rollback;
- technical documentation and release notes;
- cost, performance, reliability, and security review.

### 3.3 SEO and growth agent

Simorgh acts as a technical SEO and growth analyst:

- Search Console analysis;
- crawl, indexation, sitemap, canonical, schema, and internal-link audits;
- keyword and search-intent research;
- content-gap and competitor analysis;
- page-level optimization briefs;
- programmatic SEO planning;
- Analytics reporting, funnels, attribution, and conversion analysis;
- experiment design and measurement;
- Google Business Profile operations;
- recurring growth reports and anomaly detection.

### 3.4 Marketing and content agent

Simorgh acts as a marketing team:

- positioning, segmentation, messaging, and offers;
- campaign planning;
- editorial and social calendars;
- long-form, short-form, email, landing-page, and ad copy;
- adaptation of one source asset for multiple channels;
- creative briefs for images and video;
- campaign monitoring and post-campaign analysis;
- brand voice and reusable messaging memory.

### 3.5 Sales and customer operations agent

Simorgh acts as a sales assistant and lightweight CRM operator:

- lead capture and enrichment;
- lead scoring and qualification;
- personalized outreach drafts;
- follow-up and commitment tracking;
- meeting preparation and notes;
- proposal and quotation generation;
- pipeline summaries;
- detection of stalled opportunities;
- customer-support triage and reusable answers.

### 3.6 Personal chief of staff

- email, calendar, Slack, Notion, GitHub, Drive, and Docs coordination;
- morning and evening briefings;
- task, deadline, and commitment tracking;
- meeting preparation;
- reminders and alarms;
- personal knowledge retrieval;
- recurring and event-driven workflows.

### 3.7 Research and knowledge agent

- current web research with source attribution;
- document, PDF, spreadsheet, image, and code analysis;
- comparison of conflicting evidence;
- structured reports;
- source-aware long-term memory;
- project and relationship knowledge graphs.

## 4. Interaction modes

- Persian text chat;
- low-latency Persian voice;
- Android overlay and notification cards;
- proactive briefings;
- background missions;
- web control center for logs, approvals, workflows, memory, and costs;
- later: desktop and browser-extension surfaces.

## 5. Expert-agent topology

The user interacts with one identity, while work is delegated to specialist roles:

- executive orchestrator;
- Android operator;
- software engineer;
- DevOps and cloud engineer;
- SEO analyst;
- growth analyst;
- marketing strategist;
- content producer;
- sales operator;
- communications agent;
- researcher;
- data analyst;
- verifier and critic.

Specialists do not own credentials or execution authority directly. They create typed plans and call tools through the central runtime.

## 6. Model strategy

AvalAI is the initial model-access provider. Simorgh uses an internal provider interface so tasks can be routed among models according to:

- Persian quality;
- reasoning quality;
- coding ability;
- visual understanding;
- latency;
- context capacity;
- tool-calling reliability;
- price;
- provider availability.

The model router must support a fast model, a deep-reasoning model, a coding model, and a vision-capable model without exposing provider-specific semantics to the rest of the system.

## 7. First vertical slice

The first end-to-end milestone is deliberately narrow:

> A Persian command is received on Android, converted into a typed plan, an installed application is opened, the resulting screen state is observed, one safe UI action is executed, the post-condition is verified, and the complete trace is stored.

This slice validates the hardest architectural boundary before adding many cloud connectors.

## 8. Success criteria

- Every executed operation has a typed input and result.
- Every mobile UI action records pre-state and post-state evidence.
- Common Persian commands have a repeatable evaluation set.
- Failed operations are explicit and diagnosable.
- Long-running missions can resume after interruption.
- Model and tool usage costs can be attributed per mission.
- New connectors and application skills can be added without modifying the orchestrator core.
- Documentation and tests evolve with the implementation.
