from __future__ import annotations

from pathlib import Path

ROOT = Path("services/core")


def replace_exact(
    path: str | Path,
    old: str,
    new: str,
    *,
    label: str,
    expected: int = 1,
) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: count={count}, expected={expected}")
    file.write_text(text.replace(old, new), encoding="utf-8")


def patch_contracts() -> None:
    path = ROOT / "src/simorgh_core/agents/cancellation_contracts.py"
    replace_exact(
        path,
        "    reserved_uncertain_count: int = Field(ge=0)\n"
        "    signalled_count: int = Field(ge=0)\n",
        "    reserved_cancelled_count: int = Field(default=0, ge=0)\n"
        "    reserved_uncertain_count: int = Field(ge=0)\n"
        "    signalled_count: int = Field(ge=0)\n",
        label="reserved cancelled result count",
    )
    replace_exact(
        path,
        "            + self.pending_cancelled_count\n"
        "            + self.reserved_uncertain_count\n",
        "            + self.pending_cancelled_count\n"
        "            + self.reserved_cancelled_count\n"
        "            + self.reserved_uncertain_count\n",
        label="result count coverage",
    )


def patch_invocations() -> None:
    path = ROOT / "src/simorgh_core/agents/invocations.py"
    replace_exact(
        path,
        "    def settle_cancellation(\n"
        "        self, request_id: UUID\n"
        "    ) -> tuple[InvocationRecord, ...]: ...\n",
        "    def settle_pending_cancellation(\n"
        "        self, request_id: UUID\n"
        "    ) -> tuple[InvocationRecord, ...]: ...\n\n"
        "    def settle_reserved_cancellation(\n"
        "        self,\n"
        "        request_id: UUID,\n"
        "        *,\n"
        "        proven_not_entered: frozenset[UUID] = frozenset(),\n"
        "    ) -> tuple[InvocationRecord, ...]: ...\n\n"
        "    def settle_cancellation(\n"
        "        self, request_id: UUID\n"
        "    ) -> tuple[InvocationRecord, ...]: ...\n",
        label="invocation store cancellation protocol",
    )
    replace_exact(
        path,
        "        if parent_invocation_id is not None or attempt != 1:\n"
        "            raise InvocationStateError(\n"
        "                \"retry invocation chains are not enabled\"\n"
        "            )\n"
        "        with self._lock:\n",
        "        require_parent_shape(\n"
        "            parent_invocation_id=parent_invocation_id, attempt=attempt\n"
        "        )\n"
        "        with self._lock:\n",
        label="in-memory parent shape",
        expected=1,
    )
    replace_exact(
        path,
        "            if request_id in self._cancellation_fences:\n",
        "            if parent_invocation_id is not None:\n"
        "                parent = self._require_record_locked(parent_invocation_id)\n"
        "                require_parent_invocation(\n"
        "                    parent=parent,\n"
        "                    request_id=request_id,\n"
        "                    attempt=attempt,\n"
        "                )\n"
        "            if request_id in self._cancellation_fences:\n",
        label="in-memory parent ownership",
        expected=1,
    )
    old_settle = '''    def settle_cancellation(
        self, request_id: UUID
    ) -> tuple[InvocationRecord, ...]:
        with self._lock:
            self._require_open_locked()
            if request_id not in self._cancellation_fences:
                raise InvocationStateError(
                    "cannot settle cancellation without a durable fence"
                )
            for existing in self.list_owned(request_id=request_id, terminal=False):
                self._records[existing.invocation_id] = cancelled_invocation_record(
                    existing,
                    updated_at_ms=self._next_time(existing.updated_at_ms),
                )
            return self.list_owned(request_id=request_id)
'''
    new_settle = '''    def settle_pending_cancellation(
        self, request_id: UUID
    ) -> tuple[InvocationRecord, ...]:
        with self._lock:
            self._require_cancellation_fence_locked(request_id)
            for existing in self.list_owned(request_id=request_id, terminal=False):
                if existing.state != InvocationPhase.PENDING:
                    continue
                self._records[existing.invocation_id] = cancelled_invocation_record(
                    existing,
                    updated_at_ms=self._next_time(existing.updated_at_ms),
                )
            return self.list_owned(request_id=request_id)

    def settle_reserved_cancellation(
        self,
        request_id: UUID,
        *,
        proven_not_entered: frozenset[UUID] = frozenset(),
    ) -> tuple[InvocationRecord, ...]:
        with self._lock:
            self._require_cancellation_fence_locked(request_id)
            reserved = {
                record.invocation_id: record
                for record in self.list_owned(request_id=request_id, terminal=False)
                if record.state == InvocationPhase.RESERVED
            }
            if not proven_not_entered.issubset(reserved):
                raise InvocationConflictError(
                    "non-entry proof references a non-reserved owned invocation"
                )
            for invocation_id, existing in reserved.items():
                if (
                    invocation_id in proven_not_entered
                    and existing.effect != InvocationEffect.MUTATION
                ):
                    candidate = proven_not_entered_record(
                        existing,
                        updated_at_ms=self._next_time(existing.updated_at_ms),
                    )
                else:
                    candidate = cancelled_invocation_record(
                        existing,
                        updated_at_ms=self._next_time(existing.updated_at_ms),
                    )
                self._records[invocation_id] = candidate
            return self.list_owned(request_id=request_id)

    def settle_cancellation(
        self, request_id: UUID
    ) -> tuple[InvocationRecord, ...]:
        self.settle_pending_cancellation(request_id)
        return self.settle_reserved_cancellation(request_id)
'''
    replace_exact(
        path,
        old_settle,
        new_settle,
        label="in-memory staged cancellation settlement",
    )
    replace_exact(
        path,
        "    def _require_record_locked(self, invocation_id: UUID) -> InvocationRecord:\n",
        "    def _require_cancellation_fence_locked(self, request_id: UUID) -> None:\n"
        "        self._require_open_locked()\n"
        "        if request_id not in self._cancellation_fences:\n"
        "            raise InvocationStateError(\n"
        "                \"cannot settle cancellation without a durable fence\"\n"
        "            )\n\n"
        "    def _require_record_locked(self, invocation_id: UUID) -> InvocationRecord:\n",
        label="in-memory fence requirement",
    )
    replace_exact(
        path,
        "def ownership_reference(record: InvocationRecord) -> InvocationOwnershipReference:\n",
        "def require_parent_shape(\n"
        "    *, parent_invocation_id: UUID | None, attempt: int\n"
        ") -> None:\n"
        "    if parent_invocation_id is None and attempt != 1:\n"
        "        raise InvocationStateError(\n"
        "            \"root invocation attempt must equal one\"\n"
        "        )\n"
        "    if parent_invocation_id is not None and attempt <= 1:\n"
        "        raise InvocationStateError(\n"
        "            \"child invocation attempt must be greater than one\"\n"
        "        )\n\n\n"
        "def require_parent_invocation(\n"
        "    *, parent: InvocationRecord, request_id: UUID, attempt: int\n"
        ") -> None:\n"
        "    if parent.request_id != request_id:\n"
        "        raise InvocationConflictError(\n"
        "            \"parent invocation belongs to another task\"\n"
        "        )\n"
        "    if not parent.terminal:\n"
        "        raise InvocationStateError(\n"
        "            \"child invocation requires a terminal parent\"\n"
        "        )\n"
        "    if attempt != parent.attempt + 1:\n"
        "        raise InvocationConflictError(\n"
        "            \"child invocation attempt does not follow parent\"\n"
        "        )\n\n\n"
        "def ownership_reference(record: InvocationRecord) -> InvocationOwnershipReference:\n",
        label="explicit parent ownership helpers",
    )
    replace_exact(
        path,
        "def cancelled_invocation_record(\n",
        "def proven_not_entered_record(\n"
        "    record: InvocationRecord, *, updated_at_ms: int\n"
        ") -> InvocationRecord:\n"
        "    if record.state != InvocationPhase.RESERVED:\n"
        "        raise InvocationStateError(\n"
        "            \"non-entry proof requires a reserved invocation\"\n"
        "        )\n"
        "    return validated_record_copy(\n"
        "        record,\n"
        "        state=InvocationPhase.CANCELLED,\n"
        "        reserved_usage=_ZERO_USAGE,\n"
        "        failure_code=\"cancelled_proven_not_entered\",\n"
        "        failure_detail=(\n"
        "            \"adapter proved external execution was not entered and \"\n"
        "            \"released its reservation\"\n"
        "        ),\n"
        "        updated_at_ms=updated_at_ms,\n"
        "    )\n\n\n"
        "def cancelled_invocation_record(\n",
        label="proven non-entry terminal helper",
    )


def patch_sqlite_store() -> None:
    path = ROOT / "src/simorgh_core/agents/invocation_store.py"
    replace_exact(
        path,
        "    ownership_reference,\n"
        "    require_external_completion_reservation,\n",
        "    ownership_reference,\n"
        "    proven_not_entered_record,\n"
        "    require_external_completion_reservation,\n"
        "    require_parent_invocation,\n"
        "    require_parent_shape,\n",
        label="SQLite cancellation helper imports",
    )
    replace_exact(
        path,
        "            InvocationPhase.FAILED,\n"
        "            InvocationPhase.UNKNOWN,\n",
        "            InvocationPhase.FAILED,\n"
        "            InvocationPhase.CANCELLED,\n"
        "            InvocationPhase.UNKNOWN,\n",
        label="reserved to cancelled transition",
    )
    replace_exact(
        path,
        "        if parent_invocation_id is not None or attempt != 1:\n"
        "            raise InvocationStateError(\n"
        "                \"retry invocation chains are not enabled\"\n"
        "            )\n"
        "        with self._lock:\n",
        "        require_parent_shape(\n"
        "            parent_invocation_id=parent_invocation_id, attempt=attempt\n"
        "        )\n"
        "        with self._lock:\n",
        label="SQLite parent shape",
    )
    replace_exact(
        path,
        "            if self._get_cancellation_fence_locked(request_id) is not None:\n",
        "            if parent_invocation_id is not None:\n"
        "                parent = self._require_record_locked(parent_invocation_id)\n"
        "                require_parent_invocation(\n"
        "                    parent=parent,\n"
        "                    request_id=request_id,\n"
        "                    attempt=attempt,\n"
        "                )\n"
        "            if self._get_cancellation_fence_locked(request_id) is not None:\n",
        label="SQLite parent ownership",
        expected=1,
    )
    old = '''    def settle_cancellation(
        self, request_id: UUID
    ) -> tuple[InvocationRecord, ...]:
        with self._lock:
            self._require_healthy_locked()
            if self._get_cancellation_fence_locked(request_id) is None:
                raise InvocationStateError(
                    "cannot settle cancellation without a durable fence"
                )
            try:
                with self._transaction():
                    rows = self._connection.execute(
                        self._select_sql(
                            where_clause=(
                                "WHERE request_id = ? AND terminal = 0"
                            )
                        ),
                        (str(request_id),),
                    ).fetchall()
                    for row in rows:
                        existing = self._decode_row(row)
                        candidate = cancelled_invocation_record(
                            existing,
                            updated_at_ms=self._next_time(existing.updated_at_ms),
                        )
                        validate_invocation_transition(existing, candidate)
                        self._update_row_locked(candidate)
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked(
                    "could not settle owned invocation cancellation", exc
                )
            return self.list_owned(request_id=request_id)
'''
    new = '''    def settle_pending_cancellation(
        self, request_id: UUID
    ) -> tuple[InvocationRecord, ...]:
        with self._lock:
            self._require_cancellation_fence_locked(request_id)
            try:
                with self._transaction():
                    rows = self._connection.execute(
                        self._select_sql(
                            where_clause=(
                                "WHERE request_id = ? AND state = 'pending'"
                            )
                        ),
                        (str(request_id),),
                    ).fetchall()
                    for row in rows:
                        existing = self._decode_row(row)
                        candidate = cancelled_invocation_record(
                            existing,
                            updated_at_ms=self._next_time(existing.updated_at_ms),
                        )
                        validate_invocation_transition(existing, candidate)
                        self._update_row_locked(candidate)
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked(
                    "could not settle pending invocation cancellation", exc
                )
            return self.list_owned(request_id=request_id)

    def settle_reserved_cancellation(
        self,
        request_id: UUID,
        *,
        proven_not_entered: frozenset[UUID] = frozenset(),
    ) -> tuple[InvocationRecord, ...]:
        with self._lock:
            self._require_cancellation_fence_locked(request_id)
            try:
                with self._transaction():
                    rows = self._connection.execute(
                        self._select_sql(
                            where_clause=(
                                "WHERE request_id = ? AND state = 'reserved'"
                            )
                        ),
                        (str(request_id),),
                    ).fetchall()
                    reserved = {
                        self._decode_row(row).invocation_id: self._decode_row(row)
                        for row in rows
                    }
                    if not proven_not_entered.issubset(reserved):
                        raise InvocationConflictError(
                            "non-entry proof references a non-reserved owned invocation"
                        )
                    for invocation_id, existing in reserved.items():
                        if (
                            invocation_id in proven_not_entered
                            and existing.effect != InvocationEffect.MUTATION
                        ):
                            candidate = proven_not_entered_record(
                                existing,
                                updated_at_ms=self._next_time(
                                    existing.updated_at_ms
                                ),
                            )
                        else:
                            candidate = cancelled_invocation_record(
                                existing,
                                updated_at_ms=self._next_time(
                                    existing.updated_at_ms
                                ),
                            )
                        validate_invocation_transition(existing, candidate)
                        self._update_row_locked(candidate)
            except InvocationConflictError:
                raise
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked(
                    "could not settle reserved invocation cancellation", exc
                )
            return self.list_owned(request_id=request_id)

    def settle_cancellation(
        self, request_id: UUID
    ) -> tuple[InvocationRecord, ...]:
        self.settle_pending_cancellation(request_id)
        return self.settle_reserved_cancellation(request_id)
'''
    replace_exact(
        path,
        old,
        new,
        label="SQLite staged cancellation settlement",
    )
    replace_exact(
        path,
        "    def _get_cancellation_fence_locked(\n",
        "    def _require_cancellation_fence_locked(self, request_id: UUID) -> None:\n"
        "        self._require_healthy_locked()\n"
        "        if self._get_cancellation_fence_locked(request_id) is None:\n"
        "            raise InvocationStateError(\n"
        "                \"cannot settle cancellation without a durable fence\"\n"
        "            )\n\n"
        "    def _get_cancellation_fence_locked(\n",
        label="SQLite fence requirement",
    )


def patch_tracing() -> None:
    path = ROOT / "src/simorgh_core/agents/tracing.py"
    replace_exact(
        path,
        "    RESULT_REPLAYED = \"result_replayed\"\n",
        "    RESULT_REPLAYED = \"result_replayed\"\n"
        "    CANCELLATION_SETTLED = \"cancellation_settled\"\n"
        "    CANCELLATION_REPLAYED = \"cancellation_replayed\"\n",
        label="cancellation trace event kinds",
    )


def patch_control_plane() -> None:
    path = ROOT / "src/simorgh_core/agents/control_plane.py"
    replace_exact(
        path,
        "from simorgh_core.agents.cancellation_runtime import (\n"
        "    CancellationOwnerRegistry,\n"
        ")\n",
        "from simorgh_core.agents.cancellation_runtime import (\n"
        "    CancellationOwnerRegistry,\n"
        "    InvocationCancellationAdapterRegistry,\n"
        ")\n",
        label="control-plane adapter registry import",
    )
    replace_exact(
        path,
        "from simorgh_core.agents.task_store import (\n",
        "from simorgh_core.agents.tracing import (\n"
        "    NullTraceSink,\n"
        "    TraceEventKind,\n"
        "    TraceSink,\n"
        "    trace_event,\n"
        ")\n"
        "from simorgh_core.agents.task_store import (\n",
        label="control-plane trace imports",
    )
    replace_exact(
        path,
        "        cancellation_registry: CancellationOwnerRegistry | None = None,\n"
        "        wall_clock_millis: Callable[[], int] | None = None,\n",
        "        cancellation_registry: CancellationOwnerRegistry | None = None,\n"
        "        adapter_cancellation_registry: (\n"
        "            InvocationCancellationAdapterRegistry | None\n"
        "        ) = None,\n"
        "        trace_sink: TraceSink | None = None,\n"
        "        wall_clock_millis: Callable[[], int] | None = None,\n",
        label="control-plane cancellation dependencies",
    )
    replace_exact(
        path,
        "        self._cancellation_owners = (\n"
        "            cancellation_registry\n"
        "            or CancellationOwnerRegistry(self._invocations)\n"
        "        )\n"
        "        self._wall_clock_millis = wall_clock_millis or (\n",
        "        self._cancellation_owners = (\n"
        "            cancellation_registry\n"
        "            or CancellationOwnerRegistry(self._invocations)\n"
        "        )\n"
        "        self._adapter_cancellations = (\n"
        "            adapter_cancellation_registry\n"
        "            or InvocationCancellationAdapterRegistry(self._invocations)\n"
        "        )\n"
        "        self._trace_sink = trace_sink or NullTraceSink()\n"
        "        self._wall_clock_millis = wall_clock_millis or (\n",
        label="control-plane cancellation registry state",
    )
    replace_exact(
        path,
        "            self._invocations = store\n"
        "            self._cancellation_owners.configure_store(store)\n",
        "            self._invocations = store\n"
        "            self._cancellation_owners.configure_store(store)\n"
        "            self._adapter_cancellations.configure_store(store)\n",
        label="control-plane store registry configuration",
    )
    replace_exact(
        path,
        "            self._cancellation_owners.configure_store(\n"
        "                replacement_invocations\n"
        "            )\n",
        "            self._cancellation_owners.configure_store(\n"
        "                replacement_invocations\n"
        "            )\n"
        "            self._adapter_cancellations.configure_store(\n"
        "                replacement_invocations\n"
        "            )\n",
        label="control-plane memory reset registries",
    )
    replace_exact(
        path,
        "                if state.record.cancellation_result is not None:\n"
        "                    return state.record\n",
        "                if state.record.cancellation_result is not None:\n"
        "                    self._emit_cancellation(\n"
        "                        state.record.cancellation_result, replayed=True\n"
        "                    )\n"
        "                    return state.record\n",
        label="cancellation replay audit",
    )
    replace_exact(
        path,
        "        settled = self._invocations.settle_cancellation(request_id)\n"
        "        settled_by_id = {record.invocation_id: record for record in settled}\n",
        "        self._invocations.settle_pending_cancellation(request_id)\n"
        "        adapter_acknowledgements = (\n"
        "            await self._adapter_cancellations.cancel_owned(fence)\n"
        "        )\n"
        "        proven_not_entered = frozenset(\n"
        "            invocation_id\n"
        "            for invocation_id, acknowledgement\n"
        "            in adapter_acknowledgements.items()\n"
        "            if (\n"
        "                acknowledgement.disposition\n"
        "                == AdapterCancellationDisposition.PROVEN_NOT_ENTERED\n"
        "                and acknowledgement.usage_reservation_released\n"
        "            )\n"
        "        )\n"
        "        settled = self._invocations.settle_reserved_cancellation(\n"
        "            request_id, proven_not_entered=proven_not_entered\n"
        "        )\n"
        "        settled_by_id = {record.invocation_id: record for record in settled}\n",
        label="staged coordinator settlement",
    )
    replace_exact(
        path,
        "        reserved_uncertain_count = 0\n"
        "        signalled_count = 0\n",
        "        reserved_cancelled_count = 0\n"
        "        reserved_uncertain_count = 0\n"
        "        signalled_count = 0\n",
        label="coordinator reserved cancellation count",
    )
    replace_exact(
        path,
        "            if owned.terminal:\n"
        "                terminal_count += 1\n"
        "                adapter = AdapterCancellationDisposition.ALREADY_TERMINAL\n"
        "            elif owned.state == InvocationPhase.PENDING.value:\n"
        "                pending_cancelled_count += 1\n"
        "                adapter = AdapterCancellationDisposition.PROVEN_NOT_ENTERED\n"
        "            else:\n"
        "                reserved_uncertain_count += 1\n"
        "                adapter = AdapterCancellationDisposition.NOT_SUPPORTED\n",
        "            acknowledgement = adapter_acknowledgements.get(\n"
        "                owned.invocation_id\n"
        "            )\n"
        "            if owned.terminal:\n"
        "                terminal_count += 1\n"
        "                adapter = AdapterCancellationDisposition.ALREADY_TERMINAL\n"
        "            elif owned.state == InvocationPhase.PENDING.value:\n"
        "                pending_cancelled_count += 1\n"
        "                adapter = AdapterCancellationDisposition.PROVEN_NOT_ENTERED\n"
        "            elif final.state == InvocationPhase.CANCELLED:\n"
        "                reserved_cancelled_count += 1\n"
        "                adapter = (\n"
        "                    acknowledgement.disposition\n"
        "                    if acknowledgement is not None\n"
        "                    else AdapterCancellationDisposition.PROVEN_NOT_ENTERED\n"
        "                )\n"
        "            else:\n"
        "                reserved_uncertain_count += 1\n"
        "                adapter = (\n"
        "                    acknowledgement.disposition\n"
        "                    if acknowledgement is not None\n"
        "                    else AdapterCancellationDisposition.NOT_SUPPORTED\n"
        "                )\n",
        label="adapter acknowledgement outcome mapping",
    )
    replace_exact(
        path,
        "            pending_cancelled_count=pending_cancelled_count,\n"
        "            reserved_uncertain_count=reserved_uncertain_count,\n",
        "            pending_cancelled_count=pending_cancelled_count,\n"
        "            reserved_cancelled_count=reserved_cancelled_count,\n"
        "            reserved_uncertain_count=reserved_uncertain_count,\n",
        label="cancellation result reserved count",
    )
    replace_exact(
        path,
        "            self._persist_transition_locked(\n"
        "                state=state,\n"
        "                account=state.account,\n"
        "                record=completed_record,\n"
        "            )\n"
        "            return completed_record\n\n"
        "    async def clear_for_test",
        "            self._persist_transition_locked(\n"
        "                state=state,\n"
        "                account=state.account,\n"
        "                record=completed_record,\n"
        "            )\n"
        "            self._emit_cancellation(result, replayed=False)\n"
        "            return completed_record\n\n"
        "    def _emit_cancellation(\n"
        "        self, result: TaskCancellationResult, *, replayed: bool\n"
        "    ) -> None:\n"
        "        kind = (\n"
        "            TraceEventKind.CANCELLATION_REPLAYED\n"
        "            if replayed\n"
        "            else TraceEventKind.CANCELLATION_SETTLED\n"
        "        )\n"
        "        event = trace_event(\n"
        "            request_id=result.request.request_id,\n"
        "            kind=kind,\n"
        "            outcome=result.disposition.value,\n"
        "            reason=result.request.reason_code,\n"
        "            metadata={\n"
        "                \"cancellation_id\": str(result.request.cancellation_id),\n"
        "                \"ownership_snapshot_sha256\": (\n"
        "                    result.ownership_snapshot_sha256\n"
        "                ),\n"
        "                \"terminal_count\": result.terminal_count,\n"
        "                \"pending_cancelled_count\": (\n"
        "                    result.pending_cancelled_count\n"
        "                ),\n"
        "                \"reserved_cancelled_count\": (\n"
        "                    result.reserved_cancelled_count\n"
        "                ),\n"
        "                \"reserved_uncertain_count\": (\n"
        "                    result.reserved_uncertain_count\n"
        "                ),\n"
        "                \"signalled_count\": result.signalled_count,\n"
        "            },\n"
        "        ).model_copy(update={\"event_id\": result.audit_event_id})\n"
        "        self._trace_sink.emit(event)\n\n"
        "    async def clear_for_test",
        label="privacy-safe cancellation audit emission",
    )


def patch_api() -> None:
    path = ROOT / "src/simorgh_core/agents/api.py"
    replace_exact(
        path,
        "from simorgh_core.agents.cancellation_runtime import (\n"
        "    cancellation_owner_registry,\n"
        ")\n",
        "from simorgh_core.agents.cancellation_runtime import (\n"
        "    cancellation_owner_registry,\n"
        "    invocation_cancellation_adapter_registry,\n"
        ")\n",
        label="API adapter registry import",
    )
    replace_exact(
        path,
        "    cancellation_registry=cancellation_owner_registry,\n"
        ")\n",
        "    cancellation_registry=cancellation_owner_registry,\n"
        "    adapter_cancellation_registry=(\n"
        "        invocation_cancellation_adapter_registry\n"
        "    ),\n"
        "    trace_sink=agent_trace_sink,\n"
        ")\n",
        label="API cancellation dependencies",
    )


def write_tests() -> None:
    path = ROOT / "tests/test_cancellation_acceptance.py"
    path.write_text(
        '''from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.cancellation_contracts import (
    AdapterCancellationDisposition,
    CancellationRequesterAuthority,
    InvocationCancellationAcknowledgement,
)
from simorgh_core.agents.cancellation_runtime import (
    CancellationOwnerRegistry,
    InvocationCancellationAdapterRegistry,
)
from simorgh_core.agents.contracts import (
    ExecutionMode,
    InvocationState,
    RiskClass,
    TaskBudget,
    TaskEnvelope,
    TaskKind,
    UsageVector,
)
from simorgh_core.agents.control_plane import AgentTaskControlPlane
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocation_store import SQLiteInvocationStore
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationConflictError,
    InvocationEffect,
    InvocationKind,
)
from simorgh_core.agents.router import SpecialistRouter
from simorgh_core.agents.task_store import InMemoryAgentTaskStore
from simorgh_core.agents.tracing import InMemoryTraceSink, TraceEventKind


class FakeCancellationAdapter:
    def __init__(
        self,
        disposition: AdapterCancellationDisposition,
        *,
        release: bool = False,
        observed_at_ms: int = 2_700,
    ) -> None:
        self.disposition = disposition
        self.release = release
        self.observed_at_ms = observed_at_ms
        self.calls = 0

    async def cancel(
        self,
        *,
        invocation_id: UUID,
        cancellation_owner_id: UUID | None,
    ) -> InvocationCancellationAcknowledgement:
        self.calls += 1
        await asyncio.sleep(0)
        return InvocationCancellationAcknowledgement(
            invocation_id=invocation_id,
            cancellation_owner_id=cancellation_owner_id,
            disposition=self.disposition,
            acknowledged_at_ms=self.observed_at_ms,
            usage_reservation_released=self.release,
        )


def _task(*, marker: str = "") -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=61_000,
        locale="fa-IR",
        input_text=f"ریپازیتوری را بررسی کن {marker}",
        requested_outcome="گزارش",
        explicit_task_kind=TaskKind.REPOSITORY_RESEARCH,
        risk_class=RiskClass.READ_ONLY,
        execution_mode=ExecutionMode.READ_ONLY,
        allowed_data_sources=frozenset({"github"}),
        budget=TaskBudget(
            max_model_calls=1,
            max_tool_calls=4,
            max_input_tokens=4_000,
            max_output_tokens=1_000,
            max_estimated_cost_microusd=10_000,
            max_elapsed_ms=30_000,
            max_retries=1,
            max_parallel_branches=1,
        ),
    )


def _control(
    invocation_store,
    adapters: InvocationCancellationAdapterRegistry,
    *,
    trace_sink: InMemoryTraceSink | None = None,
) -> AgentTaskControlPlane:
    return AgentTaskControlPlane(
        router=SpecialistRouter(registry=default_specialist_registry()),
        store=InMemoryAgentTaskStore(),
        invocation_store=invocation_store,
        cancellation_registry=CancellationOwnerRegistry(invocation_store),
        adapter_cancellation_registry=adapters,
        trace_sink=trace_sink,
        wall_clock_millis=lambda: 3_000,
        monotonic_millis=lambda: 100,
    )


def _reserved_tool(store, task: TaskEnvelope, *, effect=InvocationEffect.READ_ONLY):
    owner_id = uuid4()
    record = store.begin(
        invocation_id=uuid4(),
        request_id=task.request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="tool:github.fetch-file",
        input_fingerprint="d" * 64,
        kind=InvocationKind.TOOL,
        effect=effect,
        tool_id="github.fetch-file",
        connector_id="github",
        cancellation_owner_id=owner_id,
    ).record
    reserved = store.reserve(
        invocation_id=record.invocation_id,
        usage=UsageVector(tool_calls=1),
    )
    return reserved, owner_id


@pytest.mark.asyncio
async def test_proven_non_entry_cancels_reserved_read_and_releases_usage() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    adapters = InvocationCancellationAdapterRegistry(
        store, wall_clock_millis=lambda: 2_700
    )
    task = _task()
    control = _control(store, adapters)
    await control.submit(task)
    reserved, owner_id = _reserved_tool(store, task)
    adapter = FakeCancellationAdapter(
        AdapterCancellationDisposition.PROVEN_NOT_ENTERED,
        release=True,
    )
    adapters.register(
        request_id=task.request_id,
        invocation_id=reserved.invocation_id,
        cancellation_owner_id=owner_id,
        adapter=adapter,
    )

    cancelled = await control.cancel(request_id=task.request_id, reason="لغو")

    final = store.get(reserved.invocation_id)
    assert final.state == InvocationState.CANCELLED
    assert final.committed_usage == UsageVector()
    assert adapter.calls == 1
    assert cancelled.cancellation_result is not None
    assert cancelled.cancellation_result.reserved_cancelled_count == 1
    assert cancelled.cancellation_result.reserved_uncertain_count == 0
    assert (
        cancelled.cancellation_result.outcomes[0].adapter_disposition
        == AdapterCancellationDisposition.PROVEN_NOT_ENTERED
    )


@pytest.mark.asyncio
async def test_adapter_acceptance_without_proof_remains_unknown_and_conserves_usage() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    adapters = InvocationCancellationAdapterRegistry(store)
    task = _task()
    control = _control(store, adapters)
    await control.submit(task)
    reserved, owner_id = _reserved_tool(store, task)
    adapter = FakeCancellationAdapter(AdapterCancellationDisposition.ACCEPTED)
    adapters.register(
        request_id=task.request_id,
        invocation_id=reserved.invocation_id,
        cancellation_owner_id=owner_id,
        adapter=adapter,
    )

    cancelled = await control.cancel(request_id=task.request_id, reason="لغو")

    final = store.get(reserved.invocation_id)
    assert final.state == InvocationState.UNKNOWN
    assert final.committed_usage == UsageVector(tool_calls=1)
    assert cancelled.cancellation_result is not None
    assert cancelled.cancellation_result.reserved_uncertain_count == 1


@pytest.mark.asyncio
async def test_mutation_remains_unknown_side_effect_even_with_non_entry_ack() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    adapters = InvocationCancellationAdapterRegistry(store)
    task = _task()
    control = _control(store, adapters)
    await control.submit(task)
    reserved, owner_id = _reserved_tool(
        store, task, effect=InvocationEffect.MUTATION
    )
    adapter = FakeCancellationAdapter(
        AdapterCancellationDisposition.PROVEN_NOT_ENTERED,
        release=True,
    )
    adapters.register(
        request_id=task.request_id,
        invocation_id=reserved.invocation_id,
        cancellation_owner_id=owner_id,
        adapter=adapter,
    )

    cancelled = await control.cancel(request_id=task.request_id, reason="لغو")

    assert store.get(reserved.invocation_id).state == InvocationState.UNKNOWN_SIDE_EFFECT
    assert cancelled.cancellation_result is not None
    assert cancelled.cancellation_result.reserved_uncertain_count == 1


@pytest.mark.asyncio
async def test_simultaneous_identical_cancellation_calls_adapter_once() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    adapters = InvocationCancellationAdapterRegistry(store)
    task = _task()
    control = _control(store, adapters)
    await control.submit(task)
    reserved, owner_id = _reserved_tool(store, task)
    adapter = FakeCancellationAdapter(AdapterCancellationDisposition.ACCEPTED)
    adapters.register(
        request_id=task.request_id,
        invocation_id=reserved.invocation_id,
        cancellation_owner_id=owner_id,
        adapter=adapter,
    )
    cancellation_id = uuid4()

    first, second = await asyncio.gather(
        control.cancel(
            request_id=task.request_id,
            reason="لغو همزمان",
            cancellation_id=cancellation_id,
        ),
        control.cancel(
            request_id=task.request_id,
            reason="لغو همزمان",
            cancellation_id=cancellation_id,
        ),
    )

    assert first == second
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_adapter_disable_switch_preserves_conservative_settlement() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    adapters = InvocationCancellationAdapterRegistry(store)
    adapters.disable()
    task = _task()
    control = _control(store, adapters)
    await control.submit(task)
    reserved, owner_id = _reserved_tool(store, task)
    adapter = FakeCancellationAdapter(
        AdapterCancellationDisposition.PROVEN_NOT_ENTERED,
        release=True,
    )
    adapters.register(
        request_id=task.request_id,
        invocation_id=reserved.invocation_id,
        cancellation_owner_id=owner_id,
        adapter=adapter,
    )

    cancelled = await control.cancel(request_id=task.request_id, reason="لغو")

    assert adapter.calls == 0
    assert store.get(reserved.invocation_id).state == InvocationState.UNKNOWN
    assert cancelled.cancellation_result is not None
    assert (
        cancelled.cancellation_result.outcomes[0].adapter_disposition
        == AdapterCancellationDisposition.NOT_SUPPORTED
    )


def test_parent_child_ownership_survives_sqlite_and_cross_task_parent_fails(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invocations.sqlite3"
    store = SQLiteInvocationStore(path, wall_clock_millis=lambda: 2_500)
    request_id = uuid4()
    parent = store.begin(
        invocation_id=uuid4(),
        request_id=request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="parent",
        input_fingerprint="e" * 64,
        kind=InvocationKind.SPECIALIST,
    ).record
    parent = store.complete(
        invocation_id=parent.invocation_id,
        result_payload={"ok": True},
    )
    child = store.begin(
        invocation_id=uuid4(),
        request_id=request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="child",
        input_fingerprint="f" * 64,
        kind=InvocationKind.SPECIALIST,
        parent_invocation_id=parent.invocation_id,
        attempt=2,
    ).record
    store.close()

    reopened = SQLiteInvocationStore(
        path, wall_clock_millis=lambda: 3_000, recover_interrupted=False
    )
    assert reopened.get(child.invocation_id).parent_invocation_id == parent.invocation_id
    with pytest.raises(InvocationConflictError, match="another task"):
        reopened.begin(
            invocation_id=uuid4(),
            request_id=uuid4(),
            agent_id="github.read",
            agent_version="1.0.0",
            operation="invalid-child",
            input_fingerprint="1" * 64,
            kind=InvocationKind.SPECIALIST,
            parent_invocation_id=parent.invocation_id,
            attempt=2,
        )
    reopened.close()


@pytest.mark.asyncio
async def test_cancellation_trace_excludes_operator_and_task_content() -> None:
    marker = "PRIVATE_CANCEL_MARKER_6ab"
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    adapters = InvocationCancellationAdapterRegistry(store)
    trace = InMemoryTraceSink()
    task = _task(marker=marker)
    control = _control(store, adapters, trace_sink=trace)
    await control.submit(task)

    await control.cancel(
        request_id=task.request_id,
        reason=f"لغو محرمانه {marker}",
        reason_code="operator_requested",
        requester_authority=CancellationRequesterAuthority.OPERATOR,
    )

    events = [
        event
        for event in trace.snapshot()
        if event.kind == TraceEventKind.CANCELLATION_SETTLED
    ]
    assert len(events) == 1
    encoded = events[0].model_dump_json()
    assert marker not in encoded
    assert "لغو محرمانه" not in encoded
    assert events[0].reason == "operator_requested"
''',
        encoding="utf-8",
    )


def main() -> None:
    patch_contracts()
    patch_invocations()
    patch_sqlite_store()
    patch_tracing()
    patch_control_plane()
    patch_api()
    write_tests()


if __name__ == "__main__":
    main()
