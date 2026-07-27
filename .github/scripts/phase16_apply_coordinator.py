from __future__ import annotations

from pathlib import Path

SOURCE = Path(".github/workflows/phase16-cancellation-coordinator.yml")
START_MARKER = "          python - <<'PY'\n"
END_MARKER = "\n          PY\n"


def replace_exact(
    text: str,
    old: str,
    new: str,
    *,
    label: str,
    expected: int = 1,
) -> str:
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: count={count}, expected={expected}")
    return text.replace(old, new)


def extract_embedded_source() -> str:
    source = SOURCE.read_text(encoding="utf-8")
    if source.count(START_MARKER) != 1:
        raise SystemExit("coordinator source start marker is not unique")
    remainder = source.split(START_MARKER, 1)[1]
    if remainder.count(END_MARKER) != 1:
        raise SystemExit("coordinator source end marker is not unique")
    raw = remainder.split(END_MARKER, 1)[0]
    return "\n".join(
        line[10:] if line.startswith("          ") else line
        for line in raw.splitlines()
    )


def harden_embedded_source(embedded: str) -> str:
    embedded = replace_exact(
        embedded,
        '"             previous_store.close()\\n',
        '"            previous_store.close()\\n',
        label="reset anchor indentation",
        expected=2,
    )
    embedded = replace_exact(
        embedded,
        "        input_fingerprint=(kind.value[0] * 64),",
        '        input_fingerprint=({\\n'
        '            InvocationKind.MODEL: "a",\\n'
        '            InvocationKind.TOOL: "b",\\n'
        '            InvocationKind.SPECIALIST: "c",\\n'
        '        }[kind] * 64),',
        label="test fingerprint alphabet",
    )

    api_start = embedded.index(
        'api = "services/core/src/simorgh_core/agents/api.py"'
    )
    app_start = embedded.index(
        'app = "services/core/src/simorgh_core/app.py"'
    )
    api_segment = embedded[api_start:app_start]
    api_segment = replace_exact(
        api_segment,
        "expected=1",
        "expected=2",
        label="API conflict mapping cardinality",
    )
    embedded = embedded[:api_start] + api_segment + embedded[app_start:]

    tool_start = embedded.index(
        'tool_gateway = "services/core/src/simorgh_core/agents/tool_gateway.py"'
    )
    github_start = embedded.index(
        'github_service = "services/core/src/simorgh_core/agents/github_read_service.py"'
    )
    tool_segment = embedded[tool_start:github_start]
    connector_literal = '"                connector_id=request.connector_id,\\n"'
    narrowed_literal = (
        '"                effect=InvocationEffect.READ_ONLY,\\n"\n'
        '    "                tool_id=request.tool_id,\\n"\n'
        '    "                connector_id=request.connector_id,\\n"'
    )
    tool_segment = replace_exact(
        tool_segment,
        connector_literal,
        narrowed_literal,
        label="tool gateway owner patch literals",
        expected=2,
    )
    embedded = embedded[:tool_start] + tool_segment + embedded[github_start:]

    model_start = embedded.index(
        'model_gateway = "services/core/src/simorgh_core/agents/model_gateway.py"'
    )
    github_segment = embedded[github_start:model_start]
    github_segment = replace_exact(
        github_segment,
        "task.allowed_data_sources",
        "request.allowed_data_sources",
        label="GitHub read effective data-source anchor",
        expected=2,
    )
    embedded = embedded[:github_start] + github_segment + embedded[model_start:]
    return embedded


def main() -> None:
    embedded = harden_embedded_source(extract_embedded_source())
    exec(
        compile(embedded, "phase16-coordinator.py", "exec"),
        {"__name__": "__main__"},
    )
    print("coordinator_patch_complete=true")


if __name__ == "__main__":
    main()
