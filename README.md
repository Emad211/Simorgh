# Simorgh

**Simorgh** is a Persian-first, multimodal personal agent operating system designed to help one person **build, operate, market, sell, and grow digital products** while also controlling Android applications and connected services.

> Status: foundation phase. The repository is intentionally being built from contracts, architecture, evaluation, and observability outward.

## Product thesis

Simorgh is not a chatbot. It is an event-driven agent platform composed of:

- a native Android application;
- an Android operator capable of launching apps, reading UI state, and performing verified actions;
- a model gateway backed initially by AvalAI's OpenAI-compatible API;
- specialist agents for software development, DevOps, SEO, marketing, sales, research, communication, and personal operations;
- durable workflows, memory, permissions, approvals, and audit logs;
- connectors for GitHub, Google Workspace, Slack, Notion, analytics, advertising, social platforms, browsers, and custom systems.

## Core architecture

```text
Android App / Voice / Web Console
                 |
           Simorgh API
                 |
   +-------------+-------------+
   | Orchestrator & Agent Mesh |
   | Model Router              |
   | Workflow Runtime          |
   | Memory & Knowledge        |
   | Policy / Approval / Audit |
   +-------------+-------------+
                 |
   +-------------+---------------------------+
   | AvalAI | Android Operator | Connectors  |
   +-----------------------------------------+
```

## Engineering principles

1. **API-first, UI-operation as a controlled fallback.**
2. **Plans are data:** every action uses versioned, typed contracts.
3. **Execution must be verifiable:** an action is not complete until its post-condition is observed.
4. **Persian-first:** colloquial Persian, mixed Persian-English commands, Jalali dates, RTL, and Persian evaluation suites are first-class concerns.
5. **Provider-independent:** AvalAI is the first model gateway, not a permanent architectural lock-in.
6. **Durable by design:** long-running missions survive process restarts and transient failures.
7. **Observable by default:** model calls, tool calls, costs, latency, state transitions, and failures are traceable.
8. **Documentation is part of the product.** Architecture decisions and interfaces change through ADRs and versioned specifications.

## Initial milestones

- **M0 — Engineering foundation:** contracts, API skeleton, AvalAI adapter, CI, documentation, test strategy.
- **M1 — Android vertical slice:** Persian command → plan → open app → inspect UI → perform action → verify result.
- **M2 — Personal work OS:** Gmail, Calendar, Drive, Docs, Slack, Notion, GitHub.
- **M3 — Builder OS:** coding, repository operations, CI/CD, cloud operations, product analytics.
- **M4 — Growth OS:** technical SEO, Search Console, Analytics, content, campaigns, CRM, sales workflows.
- **M5 — Proactive agent:** event monitoring, durable missions, learned routines, multi-agent reviews.

## Repository map

```text
apps/             user-facing applications
services/         deployable backend services
packages/         shared contracts and libraries
connectors/       external service integrations
docs/             product and engineering documentation
evals/            Persian, tool-use, safety, and end-to-end evaluations
infrastructure/   local and deployment configuration
```

## Current development rule

All meaningful changes should be developed on a branch and merged through a pull request with tests and updated documentation.
