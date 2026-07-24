# ADR 0002: Integrate AvalAI through a provider-neutral model adapter

- Status: Accepted
- Date: 2026-07-24

## Context

AvalAI provides access to models from multiple vendors and supports official SDKs with custom API base URLs. Model availability, names, capabilities, pricing, and provider behavior can change independently of Simorgh.

The system also needs to route different tasks to different capability classes such as fast text, deep reasoning, coding, vision, embeddings, speech, and image generation.

## Decision

All model access goes through Simorgh's `ModelProvider` and future capability interfaces. AvalAI is the first adapter and uses the official OpenAI SDK with `https://api.avalai.ir/v1` as its configurable base URL.

Model identifiers are configuration or capability-registry data. Domain agents and tools do not import the AvalAI or OpenAI SDK directly.

Simorgh will maintain its own request, usage, latency, and cost ledger. AvalAI's User API is used for reconciliation, not as the only historical record.

## Consequences

### Positive

- simple initial integration;
- access to multiple model vendors behind one provider;
- model-provider replacement without changing domain code;
- centralized retries, observability, rate handling, and cost attribution;
- capability-based routing becomes possible.

### Negative

- the common interface cannot expose every provider-specific feature automatically;
- native provider features may require optional capability extensions;
- model metadata must be refreshed and validated.

## Implementation notes

Initial environment variables:

- `AVALAI_API_KEY`
- `AVALAI_BASE_URL`
- `AVALAI_USER_API_BASE_URL`
- `AVALAI_DEFAULT_MODEL`

The API key is held by Simorgh Core and is never embedded in the Android application.
