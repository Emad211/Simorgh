package ai.simorgh.android.transport

import ai.simorgh.android.accessibility.AccessibilityCaptureController
import ai.simorgh.android.accessibility.AccessibilityObservationBus
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.protocol.DeviceObservationRefreshPayload
import ai.simorgh.android.protocol.ObservationRefreshAckStatus
import ai.simorgh.android.protocol.ObservationRefreshProtocol
import java.io.Closeable


data class ObservationRefreshReceipt(
    val status: ObservationRefreshAckStatus,
    val detail: String,
)

class AccessibilityRefreshCoordinator(
    private val publisher: AccessibilityObservationPublisher,
    private val snapshotProjector: (AccessibilitySnapshot) -> AccessibilitySnapshot = { it },
    private val captureRequester: () -> Boolean = AccessibilityCaptureController::requestCapture,
    private val terminalAcknowledgementEmitter: (
        requestId: String,
        status: ObservationRefreshAckStatus,
        detail: String,
    ) -> Unit,
    private val scheduler: ObservationScheduler = ExecutorObservationScheduler(),
) : Closeable {
    private val lock = Any()

    private var closed = false
    private var active: ActiveRefresh? = null
    private val observationSubscription = AccessibilityObservationBus.subscribe { state ->
        if (!state.serviceConnected) {
            failWaitingRefresh(
                status = ObservationRefreshAckStatus.OBSERVER_UNAVAILABLE,
                detail = "Accessibility observer disconnected during refresh",
            )
            return@subscribe
        }
        state.latestSnapshot?.let(::onSnapshot)
    }

    fun receive(
        requestEnvelopeId: String,
        rawPayload: DeviceObservationRefreshPayload,
    ): ObservationRefreshReceipt {
        val payload = runCatching {
            ObservationRefreshProtocol.validateRequest(
                requestEnvelopeId = requestEnvelopeId,
                payload = rawPayload,
            )
        }.getOrElse { error ->
            return ObservationRefreshReceipt(
                status = ObservationRefreshAckStatus.REJECTED,
                detail = error.message.orEmpty().ifBlank { "invalid refresh request" },
            )
        }

        synchronized(lock) {
            if (closed) {
                return ObservationRefreshReceipt(
                    status = ObservationRefreshAckStatus.REJECTED,
                    detail = "refresh coordinator is closed",
                )
            }
            active?.let { current ->
                return ownershipReceipt(
                    existingRequestId = current.requestId,
                    incomingRequestId = payload.requestId,
                    sameDetail = "the same refresh request already owns capture or submission",
                    otherDetail = "another refresh request owns capture or submission",
                )
            }

            val publisherRequestId = publisher.pendingRefreshRequestId()
                ?: publisher.inFlightRefreshRequestId()
            if (publisherRequestId != null) {
                return ownershipReceipt(
                    existingRequestId = publisherRequestId,
                    incomingRequestId = payload.requestId,
                    sameDetail = "the same refresh observation is queued or in flight",
                    otherDetail = "another refresh observation is queued or in flight",
                )
            }
            if (publisher.hasRefreshRequest(payload.requestId)) {
                return ObservationRefreshReceipt(
                    status = ObservationRefreshAckStatus.DUPLICATE,
                    detail = "the same refresh observation was already acknowledged",
                )
            }

            val observerState = AccessibilityObservationBus.current()
            if (!observerState.serviceConnected) {
                return ObservationRefreshReceipt(
                    status = ObservationRefreshAckStatus.OBSERVER_UNAVAILABLE,
                    detail = "Accessibility observer is not connected",
                )
            }

            val timeoutTask = scheduler.schedule(payload.timeoutMs) {
                onTimeout(payload.requestId)
            }
            active = ActiveRefresh(
                requestId = payload.requestId,
                baselineSnapshotId = observerState.latestSnapshot?.snapshotId,
                timeoutTask = timeoutTask,
            )
        }

        if (!captureRequester()) {
            return captureRequesterUnavailable(payload.requestId)
        }
        return ObservationRefreshReceipt(
            status = ObservationRefreshAckStatus.ACCEPTED,
            detail = "fresh Accessibility capture accepted",
        )
    }

    override fun close() {
        val current: ActiveRefresh?
        synchronized(lock) {
            if (closed) {
                return
            }
            closed = true
            current = active
            active = null
        }
        current?.timeoutTask?.cancel()
        observationSubscription.close()
        scheduler.close()
    }

    private fun onSnapshot(snapshot: AccessibilitySnapshot) {
        val current = synchronized(lock) {
            val candidate = active ?: return
            if (
                candidate.phase != CapturePhase.WAITING ||
                snapshot.snapshotId == candidate.baselineSnapshotId
            ) {
                return
            }
            candidate.phase = CapturePhase.SUBMITTING
            candidate.timeoutTask.cancel()
            candidate
        }

        val projected = runCatching { snapshotProjector(snapshot) }.getOrElse { error ->
            if (finishSubmitting(current.requestId)) {
                terminalAcknowledgementEmitter(
                    current.requestId,
                    ObservationRefreshAckStatus.REJECTED,
                    error.message.orEmpty().ifBlank { "snapshot projection failed" },
                )
            }
            return
        }
        val submission = publisher.submitRefresh(projected, current.requestId)
        val stillOwned = finishSubmitting(current.requestId)
        if (!stillOwned) {
            return
        }

        when (submission) {
            RefreshObservationSubmissionStatus.ACCEPTED,
            RefreshObservationSubmissionStatus.DUPLICATE,
            -> Unit

            RefreshObservationSubmissionStatus.BUSY -> terminalAcknowledgementEmitter(
                current.requestId,
                ObservationRefreshAckStatus.BUSY,
                "another refresh observation owns the publisher",
            )

            RefreshObservationSubmissionStatus.CLOSED -> terminalAcknowledgementEmitter(
                current.requestId,
                ObservationRefreshAckStatus.REJECTED,
                "observation publisher is closed",
            )

            RefreshObservationSubmissionStatus.TOO_LARGE -> terminalAcknowledgementEmitter(
                current.requestId,
                ObservationRefreshAckStatus.REJECTED,
                "fresh observation exceeds the transport byte limit",
            )
        }
    }

    private fun captureRequesterUnavailable(requestId: String): ObservationRefreshReceipt {
        val removed: ActiveRefresh?
        val progressed: Boolean
        val isClosed: Boolean
        synchronized(lock) {
            isClosed = closed
            val current = active
            progressed = current == null ||
                current.requestId != requestId ||
                current.phase == CapturePhase.SUBMITTING
            removed = if (!progressed) {
                active = null
                current
            } else {
                null
            }
        }
        removed?.timeoutTask?.cancel()

        return when {
            isClosed -> ObservationRefreshReceipt(
                status = ObservationRefreshAckStatus.REJECTED,
                detail = "refresh coordinator closed while capture was requested",
            )
            progressed -> ObservationRefreshReceipt(
                status = ObservationRefreshAckStatus.DUPLICATE,
                detail = "refresh capture already progressed before requester failure",
            )
            else -> ObservationRefreshReceipt(
                status = ObservationRefreshAckStatus.OBSERVER_UNAVAILABLE,
                detail = "Accessibility capture requester is unavailable",
            )
        }
    }

    private fun onTimeout(requestId: String) {
        val removed = removeWaiting(requestId) ?: return
        removed.timeoutTask.cancel()
        terminalAcknowledgementEmitter(
            requestId,
            ObservationRefreshAckStatus.EXPIRED,
            "no new Accessibility snapshot arrived before refresh timeout",
        )
    }

    private fun failWaitingRefresh(
        status: ObservationRefreshAckStatus,
        detail: String,
    ) {
        val removed = synchronized(lock) {
            val current = active ?: return
            if (current.phase != CapturePhase.WAITING) {
                return
            }
            active = null
            current
        }
        removed.timeoutTask.cancel()
        terminalAcknowledgementEmitter(removed.requestId, status, detail)
    }

    private fun removeWaiting(requestId: String): ActiveRefresh? = synchronized(lock) {
        val current = active ?: return@synchronized null
        if (
            current.requestId != requestId ||
            current.phase != CapturePhase.WAITING
        ) {
            return@synchronized null
        }
        active = null
        current
    }

    private fun finishSubmitting(requestId: String): Boolean = synchronized(lock) {
        val current = active ?: return@synchronized false
        if (
            current.requestId != requestId ||
            current.phase != CapturePhase.SUBMITTING
        ) {
            return@synchronized false
        }
        active = null
        !closed
    }

    private fun ownershipReceipt(
        existingRequestId: String,
        incomingRequestId: String,
        sameDetail: String,
        otherDetail: String,
    ): ObservationRefreshReceipt = ObservationRefreshReceipt(
        status = if (existingRequestId == incomingRequestId) {
            ObservationRefreshAckStatus.DUPLICATE
        } else {
            ObservationRefreshAckStatus.BUSY
        },
        detail = if (existingRequestId == incomingRequestId) sameDetail else otherDetail,
    )

    private enum class CapturePhase {
        WAITING,
        SUBMITTING,
    }

    private data class ActiveRefresh(
        val requestId: String,
        val baselineSnapshotId: String?,
        val timeoutTask: ScheduledObservationTask,
        var phase: CapturePhase = CapturePhase.WAITING,
    )
}
