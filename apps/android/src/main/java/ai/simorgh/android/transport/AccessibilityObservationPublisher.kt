package ai.simorgh.android.transport

import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.protocol.DeviceObservationAckPayload
import ai.simorgh.android.protocol.DeviceProtocol
import ai.simorgh.android.protocol.ObservationAckStatus
import ai.simorgh.android.protocol.ProtocolEnvelope
import java.io.Closeable
import java.util.UUID

class AccessibilityObservationPublisher(
    private val deviceId: String,
    private val sender: (ProtocolEnvelope) -> Boolean,
    private val listener: (String) -> Unit = {},
    private val scheduler: ObservationScheduler = ExecutorObservationScheduler(),
    private val minimumSendIntervalMillis: Long = 500,
    private val acknowledgementTimeoutMillis: Long = 10_000,
    private val maxAttempts: Int = 3,
    private val streamId: String = UUID.randomUUID().toString(),
) : Closeable {
    private val lock = Any()

    private var connected = false
    private var closed = false
    private var nextSequence = 0L
    private var lastSendAtMillis: Long? = null
    private var lastAcknowledgedFingerprint: String? = null
    private var pending: ObservationDelivery? = null
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
            if (closed || fingerprint == lastAcknowledgedFingerprint) {
                return false
            }
            if (fingerprint == inFlight?.fingerprint || fingerprint == pending?.fingerprint) {
                return false
            }

            val sequence = nextSequence
            val envelope = DeviceProtocol.observation(
                deviceId = deviceId,
                streamId = streamId,
                sequence = sequence,
                stateFingerprint = fingerprint,
                snapshot = snapshot,
            )
            if (DeviceProtocol.encodedSizeBytes(envelope) > DeviceProtocol.MAX_DEVICE_MESSAGE_BYTES) {
                listener("observation ${snapshot.snapshotId} exceeds the transport byte limit")
                return false
            }

            nextSequence += 1
            pending = ObservationDelivery(
                envelope = envelope,
                streamId = streamId,
                sequence = sequence,
                snapshotId = snapshot.snapshotId,
                fingerprint = fingerprint,
            )
            scheduleSendLocked(delayMillis = delayUntilNextSendLocked())
        }
        return true
    }

    fun setConnected(isConnected: Boolean) {
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
                return
            }
            scheduleSendLocked(delayMillis = 0)
        }
    }

    fun acknowledge(
        acknowledgement: DeviceObservationAckPayload,
        correlationId: String?,
    ): Boolean {
        synchronized(lock) {
            val active = inFlight ?: return false
            if (
                acknowledgement.streamId != active.streamId ||
                acknowledgement.sequence != active.sequence ||
                acknowledgement.snapshotId != active.snapshotId ||
                correlationId != active.envelope.messageId
            ) {
                return false
            }

            acknowledgementTask?.cancel()
            acknowledgementTask = null
            inFlight = null
            if (acknowledgement.status != ObservationAckStatus.STALE) {
                lastAcknowledgedFingerprint = active.fingerprint
            }
            listener(
                "observation ${acknowledgement.snapshotId} " +
                    acknowledgement.status.name.lowercase(),
            )
            scheduleSendLocked(delayMillis = delayUntilNextSendLocked())
            return true
        }
    }

    fun pendingSnapshotId(): String? = synchronized(lock) { pending?.snapshotId }

    fun inFlightSnapshotId(): String? = synchronized(lock) { inFlight?.snapshotId }

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
            pending = null
            inFlight = null
        }
        scheduler.close()
    }

    private fun scheduleSendLocked(delayMillis: Long) {
        if (closed || !connected || sendTask != null) {
            return
        }
        if (inFlight?.awaitingAcknowledgement == true) {
            return
        }
        if (inFlight == null && pending == null) {
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

            val active = inFlight ?: pending?.also { pending = null } ?: return
            if (active.attempts >= maxAttempts) {
                inFlight = null
                listener("observation ${active.snapshotId} failed after $maxAttempts attempts")
                scheduleSendLocked(delayMillis = delayUntilNextSendLocked())
                return
            }

            val remainingDelay = delayUntilNextSendLocked()
            if (remainingDelay > 0) {
                if (inFlight == null) {
                    pending = active
                }
                scheduleSendLocked(delayMillis = remainingDelay)
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
                listener("observation ${delivery.snapshotId} paused until reconnect")
                return
            }

            acknowledgementTask?.cancel()
            acknowledgementTask = scheduler.schedule(acknowledgementTimeoutMillis) {
                onAcknowledgementTimeout(delivery.envelope.messageId)
            }
        }
    }

    private fun onAcknowledgementTimeout(messageId: String) {
        synchronized(lock) {
            acknowledgementTask = null
            val active = inFlight ?: return
            if (active.envelope.messageId != messageId || !active.awaitingAcknowledgement) {
                return
            }
            inFlight = active.copy(awaitingAcknowledgement = false)
            listener("observation ${active.snapshotId} acknowledgement timeout")
            scheduleSendLocked(delayMillis = minimumSendIntervalMillis)
        }
    }

    private fun delayUntilNextSendLocked(): Long {
        val lastSent = lastSendAtMillis ?: return 0
        val elapsed = (scheduler.nowMillis() - lastSent).coerceAtLeast(0)
        return (minimumSendIntervalMillis - elapsed).coerceAtLeast(0)
    }

    private data class ObservationDelivery(
        val envelope: ProtocolEnvelope,
        val streamId: String,
        val sequence: Long,
        val snapshotId: String,
        val fingerprint: String,
        val attempts: Int = 0,
        val awaitingAcknowledgement: Boolean = false,
    )
}
