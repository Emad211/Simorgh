from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, *, label: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: count={count}, expected=1")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


path = "services/core/tests/test_context_compiler.py"
replace_once(
    path,
    "from uuid import UUID, uuid4\n",
    "from uuid import NAMESPACE_URL, UUID, uuid4, uuid5\n",
    label="stable routing UUID imports",
)
replace_once(
    path,
    '''    return RoutingDecision(
        request_id=task.request_id,
''',
    '''    return RoutingDecision(
        decision_id=uuid5(NAMESPACE_URL, f"simorgh-test-route:{task.request_id}"),
        request_id=task.request_id,
''',
    label="stable routing decision identity",
)
