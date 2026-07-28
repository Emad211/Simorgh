from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol
from uuid import UUID

from simorgh_core.agents.context_contracts import SpecialistContextBundle
from simorgh_core.agents.context_store import (
    ContextClaim,
    InMemoryContextStore,
    SQLiteContextStore,
)
from simorgh_core.agents.invocations import InvocationKind, InvocationRecord, InvocationStore

DEFAULT_MAX_TERMINAL_CONTEXT_RECORDS = 10_000


class ContextRetentionError(RuntimeError):
    """Terminal context retention could not be applied safely."""


class ContextRetentionStore(Protocol):
    def prune_terminal(self) -> int: ...


def terminal_context_ids_to_prune(
    *,
    contexts: Iterable[SpecialistContextBundle],
    invocations: Iterable[InvocationRecord],
    max_terminal_records: int,
    protected_context_ids: frozenset[UUID] = frozenset(),
) -> tuple[UUID, ...]:
    """Select only old contexts whose specialist invocation is durably terminal."""

    if max_terminal_records < 0:
        raise ValueError("max_terminal_records cannot be negative")
    terminal_specialists = {
        record.invocation_id
        for record in invocations
        if record.kind == InvocationKind.SPECIALIST and record.terminal
    }
    terminal_contexts = sorted(
        (
            context
            for context in contexts
            if context.specialist_invocation_id in terminal_specialists
        ),
        key=lambda context: (
            context.compiled_at_ms,
            str(context.context_bundle_id),
        ),
        reverse=True,
    )
    retained = {
        context.context_bundle_id
        for context in terminal_contexts[:max_terminal_records]
    }
    retained.update(protected_context_ids)
    return tuple(
        context.context_bundle_id
        for context in reversed(terminal_contexts)
        if context.context_bundle_id not in retained
    )


class RetentionAwareInMemoryContextStore(InMemoryContextStore):
    """In-memory context authority with bounded terminal-record retention."""

    def __init__(
        self,
        *,
        invocation_store: InvocationStore,
        max_terminal_records: int = DEFAULT_MAX_TERMINAL_CONTEXT_RECORDS,
    ) -> None:
        if max_terminal_records < 0:
            raise ValueError("max_terminal_records cannot be negative")
        super().__init__()
        self._retention_invocations = invocation_store
        self._max_terminal_records = max_terminal_records

    def claim(self, record: SpecialistContextBundle) -> ContextClaim:
        claim = super().claim(record)
        self._prune_terminal(
            protected_context_ids=frozenset({claim.record.context_bundle_id})
        )
        return claim

    def prune_terminal(self) -> int:
        return self._prune_terminal()

    def _prune_terminal(
        self,
        *,
        protected_context_ids: frozenset[UUID] = frozenset(),
    ) -> int:
        invocations = self._retention_invocations.load()
        with self._lock:
            self._require_open_locked()
            context_ids = terminal_context_ids_to_prune(
                contexts=self._records.values(),
                invocations=invocations,
                max_terminal_records=self._max_terminal_records,
                protected_context_ids=protected_context_ids,
            )
            for context_id in context_ids:
                record = self._records.pop(context_id, None)
                if record is not None:
                    self._by_invocation.pop(record.specialist_invocation_id, None)
            return len(context_ids)


class RetentionAwareSQLiteContextStore(SQLiteContextStore):
    """SQLite WAL context authority with bounded terminal-record retention."""

    def __init__(
        self,
        path: str | Path,
        *,
        invocation_store: InvocationStore,
        max_terminal_records: int = DEFAULT_MAX_TERMINAL_CONTEXT_RECORDS,
    ) -> None:
        if max_terminal_records < 0:
            raise ValueError("max_terminal_records cannot be negative")
        self._retention_invocations = invocation_store
        self._max_terminal_records = max_terminal_records
        super().__init__(path)
        try:
            self.prune_terminal()
        except BaseException:
            self.close()
            raise

    def claim(self, record: SpecialistContextBundle) -> ContextClaim:
        claim = super().claim(record)
        self._prune_terminal(
            protected_context_ids=frozenset({claim.record.context_bundle_id})
        )
        return claim

    def prune_terminal(self) -> int:
        return self._prune_terminal()

    def _prune_terminal(
        self,
        *,
        protected_context_ids: frozenset[UUID] = frozenset(),
    ) -> int:
        invocations = self._retention_invocations.load()
        with self._lock:
            self._require_healthy_locked()
            try:
                rows = self._connection.execute(
                    """
                    SELECT
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
                    FROM context_records
                    ORDER BY compiled_at_ms, context_bundle_id
                    """
                ).fetchall()
                contexts = tuple(self._decode_row(row) for row in rows)
                context_ids = terminal_context_ids_to_prune(
                    contexts=contexts,
                    invocations=invocations,
                    max_terminal_records=self._max_terminal_records,
                    protected_context_ids=protected_context_ids,
                )
                if context_ids:
                    with self._transaction():
                        for context_id in context_ids:
                            self._connection.execute(
                                "DELETE FROM context_records WHERE context_bundle_id = ?",
                                (str(context_id),),
                            )
                return len(context_ids)
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked(
                    "could not apply context retention", exc
                )


__all__ = [
    "DEFAULT_MAX_TERMINAL_CONTEXT_RECORDS",
    "ContextRetentionError",
    "ContextRetentionStore",
    "RetentionAwareInMemoryContextStore",
    "RetentionAwareSQLiteContextStore",
    "terminal_context_ids_to_prune",
]
