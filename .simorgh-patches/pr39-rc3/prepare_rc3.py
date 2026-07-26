from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ARCHIVE_SHA256 = "dde9c1eed40d319b1fde9e913b3510aa0fd4fa0e36b31436d58c8d231fa2f2a4"
ARCHIVE_BYTES = 53_811
BUNDLE_VERSION = "2026.07.26-pr39-step1.2-hardening-rc3"
CHUNK_NAMES = tuple(f"part-{index:02d}.b64" for index in range(9))
CHUNK_LENGTHS = (8_000,) * 8 + (7_748,)


def run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def reconstruct_bundle(repository: Path, temp: Path) -> Path:
    staging = repository / ".simorgh-patches/pr39-rc3"
    actual = sorted(path.name for path in staging.glob("part-*.b64"))
    if actual != list(CHUNK_NAMES):
        raise RuntimeError(f"unexpected RC3 chunk set: {actual!r}")

    pieces: list[str] = []
    for name, expected_length in zip(CHUNK_NAMES, CHUNK_LENGTHS, strict=True):
        raw = (staging / name).read_bytes()
        if len(raw) != expected_length:
            raise RuntimeError(
                f"{name}: expected {expected_length} bytes, found {len(raw)}"
            )
        pieces.append(raw.decode("ascii"))

    archive = base64.b64decode("".join(pieces), validate=True)
    if len(archive) != ARCHIVE_BYTES:
        raise RuntimeError(
            f"expected {ARCHIVE_BYTES} archive bytes, found {len(archive)}"
        )
    actual_hash = hashlib.sha256(archive).hexdigest()
    if actual_hash != ARCHIVE_SHA256:
        raise RuntimeError("RC3 archive SHA-256 mismatch")

    archive_path = temp / "pr39-rc3.zip"
    archive_path.write_bytes(archive)
    bundle = temp / "pr39-rc3-bundle"
    bundle.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive_path) as zip_file:
        bad_member = zip_file.testzip()
        if bad_member is not None:
            raise RuntimeError(f"corrupt RC3 archive member: {bad_member}")
        for info in zip_file.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"unsafe RC3 archive path: {info.filename}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise RuntimeError(f"RC3 archive symlink is forbidden: {info.filename}")
        zip_file.extractall(bundle)

    version = (bundle / "VERSION").read_text(encoding="utf-8").strip()
    if version != BUNDLE_VERSION:
        raise RuntimeError(f"unexpected RC3 version: {version!r}")
    for script in (
        bundle / "apply_pr39_complete_hardening.sh",
        bundle / "scripts/apply_pr39_complete_hardening.sh",
    ):
        script.chmod(0o755)
    return bundle


def patch_publisher(bundle: Path) -> None:
    path = bundle / "scripts/apply_pr39_hardening.py"
    text = path.read_text(encoding="utf-8")
    pairs = (
        (
            "from typing import Any, Protocol, Self\\n\n"
            "from pydantic import BaseModel, ConfigDict, Field, model_validator\\n\n"
            "from simorgh_core.agents.contracts import UsageVector\\n",
            "from typing import Any, Protocol, Self\\n"
            "from uuid import NAMESPACE_URL, UUID, uuid5\\n\n"
            "from pydantic import BaseModel, ConfigDict, Field, model_validator\\n\n"
            "from simorgh_core.agents.contracts import UsageVector\\n",
        ),
        (
            "from typing import Any, Literal, Protocol, Self, TypeAlias\\n\n"
            "from pydantic import BaseModel, ConfigDict, Field, model_validator\\n\n"
            "from simorgh_core.agents.contracts import InvocationState, UsageVector\\n",
            "from typing import Any, Literal, Protocol, Self, TypeAlias\\n"
            "from uuid import NAMESPACE_URL, UUID, uuid5\\n\n"
            "from pydantic import BaseModel, ConfigDict, Field, model_validator\\n\n"
            "from simorgh_core.agents.contracts import InvocationState, UsageVector\\n",
        ),
    )
    for old, new in pairs:
        if text.count(old) != 1 or text.count(new) != 0:
            raise RuntimeError("Publisher compatibility anchor mismatch")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


def handler_names(node: ast.expr | None) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Tuple):
        return {item.id for item in node.elts if isinstance(item, ast.Name)}
    return set()


def statement_text(lines: list[str], statement: ast.stmt, indent: str) -> str:
    segment = lines[statement.lineno - 1 : statement.end_lineno]
    return "".join(
        indent + (line[statement.col_offset :] if line.strip() else line)
        for line in segment
    )


def normalize_gateway(path: Path, gateway_error: str) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    edits: list[tuple[int, int, str]] = []
    release_count = 0
    cancel_count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try) or len(node.body) != 1 or len(node.handlers) != 1:
            continue
        statement = node.body[0]
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            continue
        handler = node.handlers[0]
        if len(handler.body) != 1 or not isinstance(handler.body[0], ast.Pass):
            continue
        call = statement.value
        func = call.func
        indent = " " * node.col_offset
        body_indent = indent + "    "
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "budget"
            and func.attr == "release"
            and handler_names(handler.type)
            == {"BudgetCancelledError", "BudgetReservationNotFoundError"}
        ):
            replacement = (
                indent
                + "with suppress(\n"
                + body_indent
                + "BudgetCancelledError,\n"
                + body_indent
                + "BudgetReservationNotFoundError,\n"
                + indent
                + "):\n"
                + statement_text(lines, statement, body_indent)
            )
            edits.append((node.lineno - 1, node.end_lineno, replacement))
            release_count += 1
        elif (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
            and func.attr == "_mark_unknown_and_settle"
            and handler_names(handler.type) == {gateway_error}
        ):
            replacement = (
                indent
                + f"with suppress({gateway_error}):\n"
                + statement_text(lines, statement, body_indent)
            )
            edits.append((node.lineno - 1, node.end_lineno, replacement))
            cancel_count += 1

    if (release_count, cancel_count) != (1, 1):
        raise RuntimeError(
            f"{path}: expected one release and cancellation Try, "
            f"found {(release_count, cancel_count)}"
        )
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start:end] = [replacement]
    updated = "".join(lines)
    if "from contextlib import suppress\n" not in updated:
        if updated.count("import asyncio\n") != 1:
            raise RuntimeError(f"{path}: asyncio import anchor mismatch")
        updated = updated.replace(
            "import asyncio\n",
            "import asyncio\nfrom contextlib import suppress\n",
            1,
        )
    path.write_text(updated, encoding="utf-8")


def normalize_product(repository: Path) -> None:
    invocations = repository / "services/core/src/simorgh_core/agents/invocations.py"
    text = invocations.read_text(encoding="utf-8")
    old_alias = "InvocationPhase: TypeAlias = InvocationState\n"
    final_alias = "InvocationPhase: TypeAlias = InvocationState  # noqa: UP040\n"
    if text.count(old_alias) != 1 or text.count(final_alias) != 0:
        raise RuntimeError("unexpected post-RC3 alias state")
    invocations.write_text(text.replace(old_alias, final_alias, 1), encoding="utf-8")

    normalize_gateway(
        repository / "services/core/src/simorgh_core/agents/model_gateway.py",
        "ModelGatewayError",
    )
    normalize_gateway(
        repository / "services/core/src/simorgh_core/agents/tool_gateway.py",
        "ToolGatewayError",
    )

    test_path = repository / "services/core/tests/test_gateway_failure_semantics_rc3.py"
    test_text = test_path.read_text(encoding="utf-8")
    old_default = "        committed_usage: UsageVector = UsageVector(),\n"
    if test_text.count(old_default) != 1:
        raise RuntimeError("B008 default anchor mismatch")
    test_path.write_text(
        test_text.replace(
            old_default,
            "        committed_usage: UsageVector | None = None,\n",
            1,
        ),
        encoding="utf-8",
    )
    run(
        "ruff",
        "check",
        "--fix",
        "--select",
        "I",
        "services/core/src/simorgh_core/agents/model_gateway.py",
        "services/core/src/simorgh_core/agents/tool_gateway.py",
        cwd=repository,
    )


def cleanup(repository: Path) -> None:
    shutil.rmtree(repository / ".simorgh-patches/pr39-rc3", ignore_errors=True)
    patches = repository / ".simorgh-patches"
    if patches.is_dir() and not any(patches.iterdir()):
        patches.rmdir()
    for relative in (
        ".github/workflows/pr39-rc3-finalize.yml",
        ".github/workflows/pr39-rc3-finalize-permission-safe.yml",
        ".github/workflows/pr39-rc3-ruff-diagnostic.yml",
        ".github/workflows/pr39-rc3-mypy-diagnostic.yml",
    ):
        (repository / relative).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    parser.add_argument("--temp", type=Path, required=True)
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    repository = args.repository.resolve()
    temp = args.temp.resolve()
    temp.mkdir(parents=True, exist_ok=True)
    bundle = reconstruct_bundle(repository, temp)
    run(sys.executable, str(bundle / "scripts/selftest_pr39_hardening_bundle.py"), cwd=repository)
    patch_publisher(bundle)
    run(
        "bash",
        str(bundle / "apply_pr39_complete_hardening.sh"),
        str(repository),
        "--dry-run",
        "--backup-dir",
        str(temp / "backups"),
        cwd=repository,
    )
    run(
        "bash",
        str(bundle / "apply_pr39_complete_hardening.sh"),
        str(repository),
        "--backup-dir",
        str(temp / "backups"),
        "--run-targeted-tests",
        cwd=repository,
    )
    normalize_product(repository)
    if args.cleanup:
        cleanup(repository)
    run("git", "diff", "--check", cwd=repository)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
