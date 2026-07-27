from __future__ import annotations

import asyncio
import time
from concurrent.futures import Future
from dataclasses import dataclass
from threading import RLock
from typing import Protocol
from uuid import UUID

from simorgh_core.agents.cancellation_contracts import (
    AdapterCancellationDisposition,
    CancellationSignalDisposition,
    InvocationCancellationAcknowledgement,
    InvocationCancellationAdapter,
    InvocationCancellationFence,
)
from simorgh_core.agents.invocations import InMemoryInvocationStore, InvocationStore


class CancellationOwnerRegistryError(RuntimeError):
    """Base class for process-local cancellation-owner failures."""


class CancellationOwnerConflictError(CancellationOwnerRegistryError):
    pass


class CancellationRegistrationBlockedError(CancellationOwnerRegistryError):
    pass


class CancellationSignalTarget(Protocol):
    def cancel(self, reason: str) -> None: ...


@dataclass(frozen=True, slots=True)
class _OwnerEntry:
    request_id: UUID
    owner_id: UUID
    target: CancellationSignalTarget


class CancellationOwnerRegistry:
    """Race-safe local signal registry backed by durable cancellation fences."""

    def __init__(self, invocation_store: InvocationStore | None = None) -> None:
        self._lock = RLock()
        self._invocations = invocation_store or InMemoryInvocationStore()
        self._entries: dict[tuple[UUID, UUID], _OwnerEntry] = {}
        self._signalled: set[tuple[UUID, UUID]] = set()

    def configure_store(self, invocation_store: InvocationStore) -> None:
        invocation_store.load()
        with self._lock:
            if self._entries:
                raise CancellationOwnerRegistryError(
                    "cannot replace invocation authority while cancellation owners are active"
                )
            self._invocations = invocation_store
            self._signalled.clear()

    def reset_to_memory(self) -> None:
        self.configure_store(InMemoryInvocationStore())

    def register(
        self,
        *,
        request_id: UUID,
        owner_id: UUID,
        target: CancellationSignalTarget,
    ) -> CancellationSignalDisposition:
        key = (request_id, owner_id)
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                if existing.target is not target:
                    raise CancellationOwnerConflictError(
                        "cancellation owner identity was registered with another target"
                    )
                return (
                    CancellationSignalDisposition.ALREADY_SIGNALLED
                    if key in self._signalled
                    else CancellationSignalDisposition.NOT_REGISTERED
                )
            fence = self._invocations.get_cancellation_fence(request_id)
            if fence is not None:
                self._attempt_signal_locked(
                    key=key,
                    target=target,
                    reason=_signal_reason(fence.request.reason_code),
                )
                raise CancellationRegistrationBlockedError(
                    "durable task cancellation blocks late owner registration"
                )
            self._entries[key] = _OwnerEntry(
                request_id=request_id,
                owner_id=owner_id,
                target=target,
            )
            return CancellationSignalDisposition.NOT_REGISTERED

    def unregister(
        self,
        *,
        request_id: UUID,
        owner_id: UUID,
        target: CancellationSignalTarget,
    ) -> None:
        key = (request_id, owner_id)
        with self._lock:
            existing = self._entries.get(key)
            if existing is None:
                return
            if existing.target is not target:
                raise CancellationOwnerConflictError(
                    "cancellation owner removal target does not match registration"
                )
            self._entries.pop(key, None)

    def signal_request(
        self,
        *,
        request_id: UUID,
        reason: str,
    ) -> dict[UUID, CancellationSignalDisposition]:
        normalized_reason = " ".join(reason.strip().split())[:1_000]
        if not normalized_reason:
            normalized_reason = "task cancellation accepted"
        with self._lock:
            keys = sorted(
                (key for key in self._entries if key[0] == request_id),
                key=lambda key: str(key[1]),
            )
            dispositions: dict[UUID, CancellationSignalDisposition] = {}
            for key in keys:
                entry = self._entries[key]
                if key in self._signalled:
                    dispositions[entry.owner_id] = (
                        CancellationSignalDisposition.ALREADY_SIGNALLED
                    )
                    continue
                dispositions[entry.owner_id] = self._attempt_signal_locked(
                    key=key,
                    target=entry.target,
                    reason=normalized_reason,
                )
            return dispositions

    def registered_owner_ids(self, request_id: UUID) -> tuple[UUID, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (owner_id for task_id, owner_id in self._entries if task_id == request_id),
                    key=str,
                )
            )

    def _attempt_signal_locked(
        self,
        *,
        key: tuple[UUID, UUID],
        target: CancellationSignalTarget,
        reason: str,
    ) -> CancellationSignalDisposition:
        if key in self._signalled:
            return CancellationSignalDisposition.ALREADY_SIGNALLED
        self._signalled.add(key)
        try:
            target.cancel(reason)
        except Exception:
            return CancellationSignalDisposition.SIGNAL_FAILED
        return CancellationSignalDisposition.SIGNALLED


class InvocationCancellationAdapterRegistryError(RuntimeError):
    """Base class for typed adapter-cancellation registry failures."""


class InvocationCancellationAdapterConflictError(
    InvocationCancellationAdapterRegistryError
):
    pass


class InvocationCancellationAdapterRegistrationBlockedError(
    InvocationCancellationAdapterRegistryError
):
    pass


@dataclass(frozen=True, slots=True)
class _AdapterEntry:
    request_id: UUID
    invocation_id: UUID
    cancellation_owner_id: UUID | None
    adapter: InvocationCancellationAdapter


class InvocationCancellationAdapterRegistry:
    """Exactly-once optional adapter cancellation behind durable task fences.

    The registry is deliberately process-local. A restart clears adapter handles and
    never pretends that an old in-memory capability still exists; durable invocation
    and task state remain authoritative.
    """

    def __init__(
        self,
        invocation_store: InvocationStore | None = None,
        *,
        wall_clock_millis: callable | None = None,
    ) -> None:
        self._lock = RLock()
        self._invocations = invocation_store or InMemoryInvocationStore()
        self._wall_clock_millis = wall_clock_millis or (
            lambda: int(time.time() * 1_000)
        )
        self._entries: dict[UUID, _AdapterEntry] = {}
        self._completed: dict[
            tuple[UUID, UUID], InvocationCancellationAcknowledgement
        ] = {}
        self._inflight: dict[
            tuple[UUID, UUID], Future[InvocationCancellationAcknowledgement]
        ] = {}
        self._enabled = True

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def disable(self) -> None:
        """Disable external cancellation hooks without disabling durable fences."""

        with self._lock:
            self._enabled = False

    def enable(self) -> None:
        with self._lock:
            self._enabled = True

    def configure_store(self, invocation_store: InvocationStore) -> None:
        invocation_store.load()
        with self._lock:
            if self._entries or self._inflight:
                raise InvocationCancellationAdapterRegistryError(
                    "cannot replace invocation authority while adapters are active"
                )
            self._invocations = invocation_store
            self._completed.clear()

    def register(
        self,
        *,
        request_id: UUID,
        invocation_id: UUID,
        cancellation_owner_id: UUID | None,
        adapter: InvocationCancellationAdapter,
    ) -> None:
        with self._lock:
            if self._invocations.get_cancellation_fence(request_id) is not None:
                raise InvocationCancellationAdapterRegistrationBlockedError(
                    "durable task cancellation blocks late adapter registration"
                )
            existing = self._entries.get(invocation_id)
            candidate = _AdapterEntry(
                request_id=request_id,
                invocation_id=invocation_id,
                cancellation_owner_id=cancellation_owner_id,
                adapter=adapter,
            )
            if existing is not None:
                if existing != candidate:
                    raise InvocationCancellationAdapterConflictError(
                        "invocation cancellation adapter identity conflicts"
                    )
                return
            self._entries[invocation_id] = candidate

    def unregister(
        self,
        *,
        request_id: UUID,
        invocation_id: UUID,
        adapter: InvocationCancellationAdapter,
    ) -> None:
        with self._lock:
            existing = self._entries.get(invocation_id)
            if existing is None:
                return
            if existing.request_id != request_id or existing.adapter is not adapter:
                raise InvocationCancellationAdapterConflictError(
                    "adapter removal identity does not match registration"
                )
            self._entries.pop(invocation_id, None)

    async def cancel_owned(
        self,
        fence: InvocationCancellationFence,
    ) -> dict[UUID, InvocationCancellationAcknowledgement]:
        with self._lock:
            entries = tuple(
                (
                    owned,
                    self._entries.get(owned.invocation_id),
                )
                for owned in fence.owned_invocations
                if not owned.terminal
            )
            enabled = self._enabled

        acknowledgements: dict[UUID, InvocationCancellationAcknowledgement] = {}
        for owned, entry in entries:
            if entry is None:
                continue
            if entry.request_id != fence.request_id:
                acknowledgements[owned.invocation_id] = self._uncertain_ack(
                    invocation_id=owned.invocation_id,
                    cancellation_owner_id=owned.cancellation_owner_id,
                )
                continue
            if not enabled:
                acknowledgements[owned.invocation_id] = (
                    InvocationCancellationAcknowledgement(
                        invocation_id=owned.invocation_id,
                        cancellation_owner_id=owned.cancellation_owner_id,
                        disposition=AdapterCancellationDisposition.NOT_SUPPORTED,
                        acknowledged_at_ms=self._now_ms(),
                    )
                )
                continue
            acknowledgements[owned.invocation_id] = await self._cancel_once(
                cancellation_id=fence.cancellation_id,
                entry=entry,
            )
        return acknowledgements

    async def _cancel_once(
        self,
        *,
        cancellation_id: UUID,
        entry: _AdapterEntry,
    ) -> InvocationCancellationAcknowledgement:
        key = (cancellation_id, entry.invocation_id)
        leader = False
        with self._lock:
            completed = self._completed.get(key)
            if completed is not None:
                return completed
            future = self._inflight.get(key)
            if future is None:
                future = Future()
                self._inflight[key] = future
                leader = True

        if not leader:
            return await asyncio.wrap_future(future)

        try:
            try:
                raw = await entry.adapter.cancel(
                    invocation_id=entry.invocation_id,
                    cancellation_owner_id=entry.cancellation_owner_id,
                )
                acknowledgement = InvocationCancellationAcknowledgement.model_validate(
                    raw.model_dump(mode="json")
                )
                if (
                    acknowledgement.invocation_id != entry.invocation_id
                    or acknowledgement.cancellation_owner_id
                    != entry.cancellation_owner_id
                ):
                    acknowledgement = self._uncertain_ack(
                        invocation_id=entry.invocation_id,
                        cancellation_owner_id=entry.cancellation_owner_id,
                    )
            except asyncio.CancelledError:
                acknowledgement = self._uncertain_ack(
                    invocation_id=entry.invocation_id,
                    cancellation_owner_id=entry.cancellation_owner_id,
                )
                raise
            except Exception:
                acknowledgement = self._uncertain_ack(
                    invocation_id=entry.invocation_id,
                    cancellation_owner_id=entry.cancellation_owner_id,
                )
        finally:
            if "acknowledgement" not in locals():
                acknowledgement = self._uncertain_ack(
                    invocation_id=entry.invocation_id,
                    cancellation_owner_id=entry.cancellation_owner_id,
                )
            with self._lock:
                self._completed[key] = acknowledgement
                self._inflight.pop(key, None)
                if not future.done():
                    future.set_result(acknowledgement)
        return acknowledgement

    def _uncertain_ack(
        self,
        *,
        invocation_id: UUID,
        cancellation_owner_id: UUID | None,
    ) -> InvocationCancellationAcknowledgement:
        return InvocationCancellationAcknowledgement(
            invocation_id=invocation_id,
            cancellation_owner_id=cancellation_owner_id,
            disposition=AdapterCancellationDisposition.UNCERTAIN,
            acknowledged_at_ms=self._now_ms(),
        )

    def _now_ms(self) -> int:
        return max(0, int(self._wall_clock_millis()))


def _signal_reason(reason_code: str) -> str:
    return f"task cancellation accepted: {reason_code}"


cancellation_owner_registry = CancellationOwnerRegistry()
invocation_cancellation_adapter_registry = InvocationCancellationAdapterRegistry()


__all__ = [
    "CancellationOwnerConflictError",
    "CancellationOwnerRegistry",
    "CancellationOwnerRegistryError",
    "CancellationRegistrationBlockedError",
    "CancellationSignalTarget",
    "InvocationCancellationAdapterConflictError",
    "InvocationCancellationAdapterRegistrationBlockedError",
    "InvocationCancellationAdapterRegistry",
    "InvocationCancellationAdapterRegistryError",
    "cancellation_owner_registry",
    "invocation_cancellation_adapter_registry",
]
