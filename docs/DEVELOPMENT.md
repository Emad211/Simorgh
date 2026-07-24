# Development Guide

## Prerequisites

- Python 3.12+
- Git
- an AvalAI API key for live model calls
- later Android work: Android Studio, current stable Android SDK, and a physical test device

## Core setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
```

Set `AVALAI_API_KEY` in `.env`. Never commit the populated file.

## Run

```bash
make run
```

The API starts at `http://127.0.0.1:8080`.

Useful endpoints:

- `GET /health`
- `POST /v1/model/text`
- interactive OpenAPI UI: `/docs`

Example model smoke test:

```bash
curl -X POST http://127.0.0.1:8080/v1/model/text \
  -H "Content-Type: application/json" \
  -d '{
    "input": "در یک جمله خودت را معرفی کن.",
    "instructions": "به فارسی پاسخ بده."
  }'
```

## Quality checks

```bash
make check
```

This runs:

- Ruff linting;
- strict mypy type checking;
- pytest.

The same checks run in GitHub Actions for pull requests and pushes to `main`.

## Contribution workflow

1. Create a focused branch.
2. Add or update tests.
3. Update relevant documentation or ADRs.
4. Run `make check`.
5. Open a draft pull request early.
6. Record unresolved risks and validation evidence in the pull request.

## Architectural changes

Create an ADR when a change:

- alters a system boundary;
- introduces a durable dependency;
- changes a public contract;
- selects a provider, runtime, database, or transport;
- changes Android observation or execution strategy.

## Model integration rules

- Application code depends on provider-neutral interfaces.
- Model names come from configuration or capability metadata.
- Prompts producing machine-consumed output must use a schema and validation.
- Invalid structured output is recorded and repaired only within a bounded retry policy.
- Live-provider tests are separate from deterministic unit tests.

## Android development rules

- Record pre-state and post-state for state-changing actions.
- Prefer stable semantic selectors over coordinates.
- Keep app-specific selectors and workflows in versioned skills.
- Never mark an action successful solely because a tap or gesture was dispatched.
- Add recorded fixtures for every fixed regression.
