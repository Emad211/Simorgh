.PHONY: install run lint typecheck test check

install:
	python -m pip install -e ".[dev]"

run:
	uvicorn simorgh_core.app:app --app-dir services/core/src --reload --host 127.0.0.1 --port 8080

lint:
	ruff check .

typecheck:
	mypy services/core/src

test:
	pytest

check: lint typecheck test
