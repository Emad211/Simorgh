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

    old_tool_patch = '''replace_count(
    tool_gateway,
    "                connector_id=request.connector_id,\n"
    "            )\n",
    "                connector_id=request.connector_id,\n"
    "                cancellation_owner_id=request.cancellation_owner_id,\n"
    "            )\n",
    expected=1,
)'''
    new_tool_patch = '''replace_count(
    tool_gateway,
    "                effect=InvocationEffect.READ_ONLY,\n"
    "                tool_id=request.tool_id,\n"
    "                connector_id=request.connector_id,\n"
    "            )\n",
    "                effect=InvocationEffect.READ_ONLY,\n"
    "                tool_id=request.tool_id,\n"
    "                connector_id=request.connector_id,\n"
    "                cancellation_owner_id=request.cancellation_owner_id,\n"
    "            )\n",
)'''
    return replace_exact(
        embedded,
        old_tool_patch,
        new_tool_patch,
        label="tool gateway owner patch",
    )


def main() -> None:
    embedded = harden_embedded_source(extract_embedded_source())
    exec(
        compile(embedded, "phase16-coordinator.py", "exec"),
        {"__name__": "__main__"},
    )
    print("coordinator_patch_complete=true")


if __name__ == "__main__":
    main()
