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
            failActive(
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
                return ObservationRefreshReceipt(
                    status = if (current.requestId == payload.requestId) {
                        ObservationRefreshAckStatus.DUPLICATE
                    } else {
                        ObservationRefreshAckStatus.BUSY
                    },
                    detail = if (current.requestId == payload.requestId) {
                        "the same refresh request already owns capture"
                    } else {
                        "another refresh request owns capture"
                    },
                )
            }

            val publisherRequestId = publisher.pendingRefreshRequestId()
                ?: publisher.inFlightRefreshRequestId()
            if (publisherRequestId != null) {
                return ObservationRefreshReceipt(
                    status = if (publisherRequestId == payload.requestId) {
                        ObservationRefreshAckStatus.DUPLICATE
                    } else {
                        ObservationRefreshAckStatus.BUSY
                    },
                    detail = if (publisherRequestId == payload.requestId) {
                        "the same refresh observation is queued or in flight"
                    } else {
                        "another refresh observation is queued or in flight"
                    },
                )
            }
            if (publisher.hasRefreshRequest(payload.requestId)) {
                return ObservationRefreshReceipt(
                    status = ObservationRefreshAckStatus.DUPLICATE,
                    detail = "the same refresh observation was already acknowledged",
                )
            }
            if (!AccessibilityObservationBus.current().serviceConnected) {
                return ObservationRefreshReceipt(
                    status = ObservationRefreshAckStatus.OBSERVER_UNAVAILABLE,
                    detail = "Accessibility observer is not connected",
                )
            }

            val baselineSnapshotId = AccessibilityObservationBus.current()
                .latestSnapshot
                ?.snapshotId
            val timeoutTask = scheduler.schedule(payload.timeoutMs) {
                onTimeout(payload.requestId)
            }
            active = ActiveRefresh(
                requestId = payload.requestId,
                baselineSnapshotId = baselineSnapshotId,
                timeoutTask = timeoutTask,
            )
        }

        if (!captureRequester()) {
            val removed = removeActive(payload.requestId)
            removed?.timeoutTask?.cancel()
            return ObservationRefreshReceipt(
                status = ObservationRefreshAckStatus.OBSERVER_UNAVAILABLE,
                detail = "Accessibility capture requester is unavailable",
            )
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
        val current: ActiveRefresh
        synchronized(lock) {
            current = active ?: return
            if (snapshot.snapshotId == current.baselineSnapshotId) {
                return
            }
            active = null
        }
        current.timeoutTask.cancel()

        val projected = snapshotProjector(snapshot)
        when (publisher.submitRefresh(projected, current.requestId)) {
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

    private fun onTimeout(requestId: String) {
        val removed = removeActive(requestId) ?: return
        removed.timeoutTask.cancel()
        terminalAcknowledgementEmitter(
            requestId,
            ObservationRefreshAckStatus.EXPIRED,
            "no new Accessibility snapshot arrived before refresh timeout",
        )
    }

    private fun failActive(
        status: ObservationRefreshAckStatus,
        detail: String,
    ) {
        val removed: ActiveRefresh
        synchronized(lock) {
            removed = active ?: return
            active = null
        }
        removed.timeoutTask.cancel()
        terminalAcknowledgementEmitter(removed.requestId, status, detail)
    }

    private fun removeActive(requestId: String): ActiveRefresh? = synchronized(lock) {
        val current = active ?: return@synchronized null
        if (current.requestId != requestId) {
            return@synchronized null
        }
        active = null
        current
    }

    private data class ActiveRefresh(
        val requestId: String,
        val baselineSnapshotId: String?,
        val timeoutTask: ScheduledObservationTask,
    )
}
