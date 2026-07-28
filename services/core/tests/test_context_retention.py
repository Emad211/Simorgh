from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from simorgh_core.agents.context_contracts import SpecialistContextBundle
from simorgh_core.agents.context_retention import (
    RetentionAwareInMemoryContextStore,
    RetentionAwareSQLiteContextStore,
    terminal_context_ids_to_prune,
)
from simorgh_core.agents.contracts import InvocationState
from simorgh_core.agents.invocations import (
    InvocationKind,
    InvocationRecord,
    InvocationStore,
)


class _InvocationSnapshot:
    def __init__(self, records: tuple[InvocationRecord, ...]) -> None:
        self._records = records

    def load(self) -> list[InvocationRecord]:
        return list(self._records)


def _invocation(*, invocation_id: UUID, terminal: bool) -> InvocationRecord:
    return InvocationRecord.model_construct(
        invocation_id=invocation_id,
        kind=InvocationKind.SPECIALIST,
        state=(InvocationState.COMPLETED if terminal else InvocationState.PENDING),
    )


def _context(
    *,
    context_bundle_id: UUID,
    invocation_id: UUID,
    compiled_at_ms: int,
) -> SpecialistContextBundle:
    return SpecialistContextBundle.model_construct(
        context_bundle_id=context_bundle_id,
        specialist_invocation_id=invocation_id,
        compiled_at_ms=compiled_at_ms,
    )


def test_retention_selector_prunes_only_old_terminal_specialist_contexts() -> None:
    old_context_id = uuid4()
    newest_context_id = uuid4()
    active_context_id = uuid4()
    old_invocation_id = uuid4()
    newest_invocation_id = uuid4()
    active_invocation_id = uuid4()
    contexts = (
        _context(
            context_bundle_id=old_context_id,
            invocation_id=old_invocation_id,
            compiled_at_ms=1_000,
        ),
        _context(
            context_bundle_id=newest_context_id,
            invocation_id=newest_invocation_id,
            compiled_at_ms=2_000,
        ),
        _context(
            context_bundle_id=active_context_id,
            invocation_id=active_invocation_id,
            compiled_at_ms=500,
        ),
    )
    invocations = (
        _invocation(invocation_id=old_invocation_id, terminal=True),
        _invocation(invocation_id=newest_invocation_id, terminal=True),
        _invocation(invocation_id=active_invocation_id, terminal=False),
    )

    selected = terminal_context_ids_to_prune(
        contexts=contexts,
        invocations=invocations,
        max_terminal_records=1,
    )

    assert selected == (old_context_id,)
    assert active_context_id not in selected


def test_current_claim_protection_can_temporarily_preserve_terminal_context() -> None:
    context_id = uuid4()
    invocation_id = uuid4()

    selected = terminal_context_ids_to_prune(
        contexts=(
            _context(
                context_bundle_id=context_id,
                invocation_id=invocation_id,
                compiled_at_ms=1_000,
            ),
        ),
        invocations=(_invocation(invocation_id=invocation_id, terminal=True),),
        max_terminal_records=0,
        protected_context_ids=frozenset({context_id}),
    )

    assert selected == ()


def test_in_memory_retention_removes_old_terminal_but_keeps_nonterminal() -> None:
    old_context_id = uuid4()
    active_context_id = uuid4()
    old_invocation_id = uuid4()
    active_invocation_id = uuid4()
    invocation_store = cast(
        InvocationStore,
        _InvocationSnapshot(
            (
                _invocation(invocation_id=old_invocation_id, terminal=True),
                _invocation(invocation_id=active_invocation_id, terminal=False),
            )
        ),
    )
    store = RetentionAwareInMemoryContextStore(
        invocation_store=invocation_store,
        max_terminal_records=0,
    )
    records = cast(dict[UUID, SpecialistContextBundle], cast(Any, store)._records)
    by_invocation = cast(dict[UUID, UUID], cast(Any, store)._by_invocation)
    old_context = _context(
        context_bundle_id=old_context_id,
        invocation_id=old_invocation_id,
        compiled_at_ms=1_000,
    )
    active_context = _context(
        context_bundle_id=active_context_id,
        invocation_id=active_invocation_id,
        compiled_at_ms=500,
    )
    records[old_context_id] = old_context
    records[active_context_id] = active_context
    by_invocation[old_invocation_id] = old_context_id
    by_invocation[active_invocation_id] = active_context_id

    assert store.prune_terminal() == 1
    assert set(records) == {active_context_id}
    assert set(by_invocation) == {active_invocation_id}


class _SQLiteRetentionFixture(RetentionAwareSQLiteContextStore):
    def __init__(
        self,
        path: Path,
        *,
        invocation_store: InvocationStore,
        max_terminal_records: int,
    ) -> None:
        self._fixture_contexts: dict[str, SpecialistContextBundle] = {}
        super().__init__(
            path,
            invocation_store=invocation_store,
            max_terminal_records=max_terminal_records,
        )

    def add_fixture(self, context: SpecialistContextBundle) -> None:
        context_id = str(context.context_bundle_id)
        self._fixture_contexts[context_id] = context
        payload = "{}"
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        cast(Any, self)._connection.execute(
            """
            INSERT INTO context_records (
                context_bundle_id,
                request_id,
                specialist_invocation_id,
                agent_id,
                agent_version,
                canonical_sha256,
                compiled_at_ms,
                privacy,
                retention,
                total_bytes,
                estimated_tokens,
                payload_json,
                payload_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                context_id,
                str(uuid4()),
                str(context.specialist_invocation_id),
                "fixture.agent",
                "1.0.0",
                "a" * 64,
                context.compiled_at_ms,
                "internal",
                "session",
                1,
                1,
                payload,
                payload_hash,
            ),
        )

    def stored_ids(self) -> set[UUID]:
        rows = cast(Any, self)._connection.execute(
            "SELECT context_bundle_id FROM context_records"
        ).fetchall()
        return {UUID(str(row["context_bundle_id"])) for row in rows}

    def _decode_row(self, row: Any) -> SpecialistContextBundle:
        return self._fixture_contexts[str(row["context_bundle_id"])]


def test_sqlite_retention_deletes_only_old_terminal_rows(tmp_path: Path) -> None:
    old_context_id = uuid4()
    newest_context_id = uuid4()
    active_context_id = uuid4()
    old_invocation_id = uuid4()
    newest_invocation_id = uuid4()
    active_invocation_id = uuid4()
    invocation_store = cast(
        InvocationStore,
        _InvocationSnapshot(
            (
                _invocation(invocation_id=old_invocation_id, terminal=True),
                _invocation(invocation_id=newest_invocation_id, terminal=True),
                _invocation(invocation_id=active_invocation_id, terminal=False),
            )
        ),
    )
    store = _SQLiteRetentionFixture(
        tmp_path / "contexts.sqlite3",
        invocation_store=invocation_store,
        max_terminal_records=1,
    )
    store.add_fixture(
        _context(
            context_bundle_id=old_context_id,
            invocation_id=old_invocation_id,
            compiled_at_ms=1_000,
        )
    )
    store.add_fixture(
        _context(
            context_bundle_id=newest_context_id,
            invocation_id=newest_invocation_id,
            compiled_at_ms=2_000,
        )
    )
    store.add_fixture(
        _context(
            context_bundle_id=active_context_id,
            invocation_id=active_invocation_id,
            compiled_at_ms=500,
        )
    )

    assert store.prune_terminal() == 1
    assert store.stored_ids() == {newest_context_id, active_context_id}
    store.close()
