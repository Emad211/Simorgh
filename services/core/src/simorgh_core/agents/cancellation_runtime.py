from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Protocol
from uuid import UUID

from simorgh_core.agents.cancellation_contracts import CancellationSignalDisposition
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


def _signal_reason(reason_code: str) -> str:
    return f"task cancellation accepted: {reason_code}"


cancellation_owner_registry = CancellationOwnerRegistry()


__all__ = [
    "CancellationOwnerConflictError",
    "CancellationOwnerRegistry",
    "CancellationOwnerRegistryError",
    "CancellationRegistrationBlockedError",
    "CancellationSignalTarget",
    "cancellation_owner_registry",
]
