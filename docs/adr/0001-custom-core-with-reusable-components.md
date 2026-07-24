# ADR 0001: Build a custom Simorgh core and reuse external components at boundaries

- Status: Accepted
- Date: 2026-07-24

## Context

Existing personal-agent and mobile-automation projects provide valuable implementations, but Simorgh requires a specific combination of Persian-first interaction, Android operation, development, SEO, marketing, sales, durable missions, provider routing, memory, and verifiable execution.

Building directly inside an external agent framework would couple product contracts, memory, workflows, and provider semantics to that project's release cycle and architectural assumptions.

## Decision

Build Simorgh Core as an independent service with its own versioned contracts for actions, observations, results, connectors, workflows, and memory.

External projects may be used as:

- implementation references;
- separately deployed adapters;
- imported libraries where their licenses and boundaries are appropriate;
- prototypes for narrow subsystems.

They are not the source of truth for Simorgh's domain model or execution state.

## Consequences

### Positive

- control over the critical execution and verification model;
- provider and framework independence;
- easier scientific evaluation across alternative implementations;
- clearer ownership of Persian behavior and mobile traces;
- ability to replace workflow, model, or connector runtimes independently.

### Negative

- more foundation work before feature breadth;
- responsibility for maintaining core infrastructure;
- deliberate integration work instead of inheriting a complete opinionated stack.

## Review trigger

Reconsider only if an external runtime fully satisfies Simorgh's public contracts, verification requirements, persistence model, and provider independence without invasive changes.
