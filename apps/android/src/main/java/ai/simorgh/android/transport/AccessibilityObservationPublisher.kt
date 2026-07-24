package ai.simorgh.android.transport

import ai.simorgh.android.accessibility.AccessibilityAcknowledgementBus
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.accessibility.AcknowledgedAccessibilityObservation
import ai.simorgh.android.protocol.DeviceObservationAckPayload
import ai.simorgh.android.protocol.DeviceProtocol
import ai.simorgh.android.protocol.ObservationAckStatus
import ai.simorgh.android.protocol.ObservationRefreshProtocol
import ai.simorgh.android.protocol.ProtocolEnvelope
import java.io.Closeable
import java.util.ArrayDeque
import java.util.UUID

enum class RefreshObservationSubmissionStatus {
    ACCEPTED,
    DUPLICATE,
    BUSY,
    CLOSED,
    TOO_LARGE,
}

class AccessibilityObservationPublisher(
    private val deviceId: String,
    private val sender: (ProtocolEnvelope) -> Boolean,
    private val listener: (String) -> Unit = {},
    private val acknowledgementListener: (AcknowledgedAccessibilityObservation) -> Unit = {},
    private val acknowledgementInvalidator: () -> Unit = AccessibilityAcknowledgementBus::reset,
    private val scheduler: ObservationScheduler = ExecutorObservationScheduler(),
    private val minimumSendIntervalMillis: Long = 500,
    private val acknowledgementTimeoutMillis: Long = 10_000,
    private val maxAttempts: Int = 3,
    private val streamId: String = UUID.randomUUID().toString(),
) : Closeable {
    private val lock = Any()
    private val recentRefreshRequestIds = ArrayDeque<String>()

    private var connected = false
    private var closed = false
    private var nextSequence = 0L
    private var lastSendAtMillis: Long? = null
    private var lastAcknowledgedFingerprint: String? = null
    private var latestSnapshot: AccessibilitySnapshot? = null
    private var pendingNormal: PendingObservation? = null
    private var pendingRefresh: PendingObservation? = null
    private var inFlight: ObservationDelivery? = null
    private var sendTask: ScheduledObservationTask? = null
    private var acknowledgementTask: ScheduledObservationTask? = null

    init {
        require(minimumSendIntervalMillis >= 0)
        require(acknowledgementTimeoutMillis > 0)
        require(maxAttempts > 0)
        require(runCatching { UUID.fromString(streamId) }.isSuccess)
    }

    fun submit(snapshot: AccessibilitySnapshot): Boolean {
        val fingerprint = AccessibilitySnapshotFingerprint.calculate(snapshot)

        synchronized(lock) {
            if (closed) {
                return false
            }
            if (fingerprint == lastAcknowledgedFingerprint) {
                latestSnapshot = snapshot
                return false
            }
            if (
                fingerprint == inFlight?.fingerprint ||
                fingerprint == pendingNormal?.fingerprint ||
                fingerprint == pendingRefresh?.fingerprint
            ) {
                latestSnapshot = snapshot
                return false
            }

            val pending = PendingObservation(
                snapshot = snapshot,
                fingerprint = fingerprint,
            )
            if (!fitsTransportLimitLocked(pending)) {
                listener("observation ${snapshot.snapshotId} exceeds the transport byte limit")
                return false
            }

            latestSnapshot = snapshot
            pendingNormal = pending
            scheduleSendLocked(delayMillis = delayUntilNextSendLocked())
        }
        return true
    }

    fun submitRefresh(
        snapshot: AccessibilitySnapshot,
        refreshRequestId: String,
    ): RefreshObservationSubmissionStatus {
        require(runCatching { UUID.fromString(refreshRequestId) }.isSuccess) {
            "refresh request id must be a UUID"
        }
        val fingerprint = AccessibilitySnapshotFingerprint.calculate(snapshot)

        synchronized(lock) {
            if (closed) {
                return RefreshObservationSubmissionStatus.CLOSED
            }
            if (hasRefreshRequestLocked(refreshRequestId)) {
                return RefreshObservationSubmissionStatus.DUPLICATE
            }
            if (activeRefreshRequestIdLocked() != null) {
                return RefreshObservationSubmissionStatus.BUSY
            }

            val pending = PendingObservation(
                snapshot = snapshot,
                fingerprint = fingerprint,
                refreshRequestId = refreshRequestId,
            )
            if (!fitsTransportLimitLocked(pending)) {
                listener(
                    "refresh observation ${snapshot.snapshotId} exceeds the transport byte limit",
                )
                return RefreshObservationSubmissionStatus.TOO_LARGE
            }

            latestSnapshot = snapshot
            // The explicit capture is newer than any unsent ordinary state and supersedes it.
            pendingNormal = null
            pendingRefresh = pending
            scheduleSendLocked(delayMillis = delayUntilNextSendLocked())
        }
        return RefreshObservationSubmissionStatus.ACCEPTED
    }

    fun hasRefreshRequest(refreshRequestId: String): Boolean = synchronized(lock) {
        hasRefreshRequestLocked(refreshRequestId)
    }

    fun activeRefreshRequestId(): String? = synchronized(lock) {
        activeRefreshRequestIdLocked()
    }

    fun setConnected(isConnected: Boolean) {
        var invalidateAcknowledgement = false
        synchronized(lock) {
            if (closed || connected == isConnected) {
                return
            }
            connected = isConnected
            sendTask?.cancel()
            sendTask = null
            acknowledgementTask?.cancel()
            acknowledgementTask = null

            if (!connected) {
                inFlight = inFlight?.copy(awaitingAcknowledgement = false)
                invalidateAcknowledgement = true
            } else {
                lastAcknowledgedFingerprint = null
                if (inFlight == null && pendingRefresh == null && pendingNormal == null) {
                    latestSnapshot?.let { snapshot ->
                        pendingNormal = PendingObservation(
                            snapshot = snapshot,
                            fingerprint = AccessibilitySnapshotFingerprint.calculate(snapshot),
                        )
                    }
                }
                scheduleSendLocked(delayMillis = 0)
            }
        }
        if (invalidateAcknowledgement) {
            acknowledgementInvalidator()
        }
    }

    fun acknowledge(
        acknowledgement: DeviceObservationAckPayload,
        correlationId: String?,
    ): Boolean {
        var published: AcknowledgedAccessibilityObservation? = null
        synchronized(lock) {
            val active = inFlight ?: return false
            if (
                acknowledgement.streamId != active.streamId ||
                acknowledgement.sequence != active.sequence ||
                acknowledgement.snapshotId != active.snapshot.snapshotId ||
                correlationId != active.envelope.messageId
            ) {
                return false
            }

            acknowledgementTask?.cancel()
            acknowledgementTask = null
            inFlight = null
            if (acknowledgement.status != ObservationAckStatus.STALE) {
                lastAcknowledgedFingerprint = active.fingerprint
                published = AcknowledgedAccessibilityObservation(
                    streamId = active.streamId,
                    sequence = active.sequence,
                    stateFingerprint = active.fingerprint,
                    snapshot = active.snapshot,
                    acknowledgedAtMs = acknowledgement.receivedAtMs,
                )
            }
            active.refreshRequestId?.let(::rememberRefreshRequestLocked)
            listener(
                "observation ${acknowledgement.snapshotId} " +
                    acknowledgement.status.name.lowercase(),
            )
            scheduleSendLocked(delayMillis = delayUntilNextSendLocked())
        }
        published?.let(acknowledgementListener)
        return true
    }

    fun pendingSnapshotId(): String? = synchronized(lock) {
        (pendingRefresh ?: pendingNormal)?.snapshot?.snapshotId
    }

    fun pendingRefreshRequestId(): String? = synchronized(lock) {
        pendingRefresh?.refreshRequestId
    }

    fun inFlightSnapshotId(): String? = synchronized(lock) { inFlight?.snapshot?.snapshotId }

    fun inFlightRefreshRequestId(): String? = synchronized(lock) {
        inFlight?.refreshRequestId
    }

    override fun close() {
        synchronized(lock) {
            if (closed) {
                return
            }
            closed = true
            connected = false
            sendTask?.cancel()
            acknowledgementTask?.cancel()
            sendTask = null
            acknowledgementTask = null
            latestSnapshot = null
            pendingNormal = null
            pendingRefresh = null
            inFlight = null
            recentRefreshRequestIds.clear()
        }
        acknowledgementInvalidator()
        scheduler.close()
    }

    private fun scheduleSendLocked(delayMillis: Long) {
        if (closed || !connected || sendTask != null) {
            return
        }
        if (inFlight?.awaitingAcknowledgement == true) {
            return
        }
        if (inFlight == null && pendingRefresh == null && pendingNormal == null) {
            return
        }

        sendTask = scheduler.schedule(delayMillis) {
            synchronized(lock) {
                sendTask = null
            }
            attemptSend()
        }
    }

    private fun attemptSend() {
        val delivery: ObservationDelivery
        synchronized(lock) {
            if (closed || !connected) {
                return
            }

            val remainingDelay = delayUntilNextSendLocked()
            if (remainingDelay > 0) {
                scheduleSendLocked(delayMillis = remainingDelay)
                return
            }

            val active = inFlight ?: materializeNextLocked() ?: return
            if (active.attempts >= maxAttempts) {
                inFlight = null
                listener(
                    "observation ${active.snapshot.snapshotId} failed after $maxAttempts attempts",
                )
                scheduleSendLocked(delayMillis = delayUntilNextSendLocked())
                return
            }

            delivery = active.copy(
                attempts = active.attempts + 1,
                awaitingAcknowledgement = true,
            )
            inFlight = delivery
            lastSendAtMillis = scheduler.nowMillis()
        }

        val sent = sender(delivery.envelope)
        var invalidateAcknowledgement = false
        synchronized(lock) {
            if (closed || inFlight?.envelope?.messageId != delivery.envelope.messageId) {
                return
            }
            if (!sent) {
                connected = false
                inFlight = delivery.copy(
                    attempts = (delivery.attempts - 1).coerceAtLeast(0),
                    awaitingAcknowledgement = false,
                )
                listener("observation ${delivery.snapshot.snapshotId} paused until reconnect")
                invalidateAcknowledgement = true
            } else {
                acknowledgementTask?.cancel()
                acknowledgementTask = scheduler.schedule(acknowledgementTimeoutMillis) {
                    onAcknowledgementTimeout(delivery.envelope.messageId)
                }
            }
        }
        if (invalidateAcknowledgement) {
            acknowledgementInvalidator()
        }
    }

    private fun materializeNextLocked(): ObservationDelivery? {
        val pending = pendingRefresh?.also { pendingRefresh = null }
            ?: pendingNormal?.also { pendingNormal = null }
            ?: return null
        val sequence = nextSequence
        val envelope = if (pending.refreshRequestId == null) {
            DeviceProtocol.observation(
                deviceId = deviceId,
                streamId = streamId,
                sequence = sequence,
                stateFingerprint = pending.fingerprint,
                snapshot = pending.snapshot,
            )
        } else {
            ObservationRefreshProtocol.correlatedObservation(
                deviceId = deviceId,
                refreshEnvelopeId = pending.refreshRequestId,
                streamId = streamId,
                sequence = sequence,
                stateFingerprint = pending.fingerprint,
                snapshot = pending.snapshot,
            )
        }
        nextSequence += 1
        return ObservationDelivery(
            envelope = envelope,
            streamId = streamId,
            sequence = sequence,
            snapshot = pending.snapshot,
            fingerprint = pending.fingerprint,
            refreshRequestId = pending.refreshRequestId,
        )
    }

    private fun fitsTransportLimitLocked(pending: PendingObservation): Boolean {
        // Long.MAX_VALUE is the largest serialized sequence width the live envelope can reach.
        val previewSequence = Long.MAX_VALUE
        val preview = if (pending.refreshRequestId == null) {
            DeviceProtocol.observation(
                deviceId = deviceId,
                streamId = streamId,
                sequence = previewSequence,
                stateFingerprint = pending.fingerprint,
                snapshot = pending.snapshot,
            )
        } else {
            ObservationRefreshProtocol.correlatedObservation(
                deviceId = deviceId,
                refreshEnvelopeId = pending.refreshRequestId,
                streamId = streamId,
                sequence = previewSequence,
                stateFingerprint = pending.fingerprint,
                snapshot = pending.snapshot,
            )
        }
        return DeviceProtocol.encodedSizeBytes(preview) <= DeviceProtocol.MAX_DEVICE_MESSAGE_BYTES
    }

    private fun onAcknowledgementTimeout(messageId: String) {
        synchronized(lock) {
            acknowledgementTask = null
            val active = inFlight ?: return
            if (active.envelope.messageId != messageId || !active.awaitingAcknowledgement) {
                return
            }
            inFlight = active.copy(awaitingAcknowledgement = false)
            listener(
                "observation ${active.snapshot.snapshotId} acknowledgement timeout",
            )
            scheduleSendLocked(delayMillis = minimumSendIntervalMillis)
        }
    }

    private fun delayUntilNextSendLocked(): Long {
        val lastSent = lastSendAtMillis ?: return 0
        val elapsed = (scheduler.nowMillis() - lastSent).coerceAtLeast(0)
        return (minimumSendIntervalMillis - elapsed).coerceAtLeast(0)
    }

    private fun activeRefreshRequestIdLocked(): String? =
        inFlight?.refreshRequestId ?: pendingRefresh?.refreshRequestId

    private fun hasRefreshRequestLocked(refreshRequestId: String): Boolean =
        activeRefreshRequestIdLocked() == refreshRequestId ||
            recentRefreshRequestIds.contains(refreshRequestId)

    private fun rememberRefreshRequestLocked(refreshRequestId: String) {
        recentRefreshRequestIds.remove(refreshRequestId)
        recentRefreshRequestIds.addLast(refreshRequestId)
        while (recentRefreshRequestIds.size > MAX_RECENT_REFRESH_REQUESTS) {
            recentRefreshRequestIds.removeFirst()
        }
    }

    private data class PendingObservation(
        val snapshot: AccessibilitySnapshot,
        val fingerprint: String,
        val refreshRequestId: String? = null,
    )

    private data class ObservationDelivery(
        val envelope: ProtocolEnvelope,
        val streamId: String,
        val sequence: Long,
        val snapshot: AccessibilitySnapshot,
        val fingerprint: String,
        val refreshRequestId: String? = null,
        val attempts: Int = 0,
        val awaitingAcknowledgement: Boolean = false,
    )

    private companion object {
        const val MAX_RECENT_REFRESH_REQUESTS = 32
    }
}
