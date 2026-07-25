package ai.simorgh.android.time

import android.os.SystemClock
import java.util.LinkedHashMap
import java.util.UUID
import java.util.concurrent.atomic.AtomicLong

enum class CoreClockSyncFailureKind {
    INACTIVE_GENERATION,
    INVALID_IDENTITY,
    UNKNOWN_PROBE,
    SEQUENCE_MISMATCH,
    SAMPLE_REJECTED,
}

data class CoreClockSyncOutcome(
    val accepted: Boolean,
    val fatal: Boolean,
    val failureKind: CoreClockSyncFailureKind? = null,
    val reading: CoreClockReading? = null,
    val wallClockJumpDetected: Boolean = false,
    val coreDiscontinuityDetected: Boolean = false,
    val detail: String,
)

/**
 * Owns request/response boundaries used to estimate Core epoch time.
 *
 * Every physical WebSocket attempt receives an external generation used to reject stale socket
 * callbacks. The shared estimator receives a separate process-wide generation so two client
 * instances can never invalidate one another by reusing the same local counter value.
 */
class CoreClockSynchronizer(
    private val estimator: CoreClockEstimator = CoreClockBus.estimator,
    private val monotonicMillis: () -> Long = SystemClock::elapsedRealtime,
    private val wallClockMillis: () -> Long = System::currentTimeMillis,
    private val maxPendingHeartbeatProbes: Int = DEFAULT_MAX_PENDING_HEARTBEAT_PROBES,
) {
    private val lock = Any()
    private val heartbeatProbes = LinkedHashMap<String, HeartbeatProbe>()

    private var activeGeneration: Long? = null
    private var activeEstimatorGeneration: Long? = null
    private var registrationProbe: RegistrationProbe? = null

    init {
        require(maxPendingHeartbeatProbes in 1..1_024)
    }

    fun beginGeneration(generation: Long) {
        require(generation >= 0)
        val estimatorGeneration = CoreClockGenerationSequence.next()
        synchronized(lock) {
            activeGeneration = generation
            activeEstimatorGeneration = estimatorGeneration
            registrationProbe = null
            heartbeatProbes.clear()
            estimator.beginGeneration(estimatorGeneration)
        }
    }

    fun invalidate(expectedGeneration: Long? = null) {
        synchronized(lock) {
            val current = activeGeneration
            if (
                current == null ||
                (expectedGeneration != null && expectedGeneration != current)
            ) {
                return
            }
            val estimatorGeneration = activeEstimatorGeneration
            activeGeneration = null
            activeEstimatorGeneration = null
            registrationProbe = null
            heartbeatProbes.clear()
            estimator.invalidate(estimatorGeneration)
        }
    }

    fun markRegistrationSent(
        generation: Long,
        messageId: String,
    ): Boolean {
        if (!isUuid(messageId)) {
            return false
        }
        val sentAt = monotonicMillis().coerceAtLeast(0)
        return synchronized(lock) {
            if (activeGeneration != generation || activeEstimatorGeneration == null) {
                return@synchronized false
            }
            registrationProbe = RegistrationProbe(
                generation = generation,
                messageId = messageId,
                sentAtElapsedMs = sentAt,
            )
            true
        }
    }

    fun discardRegistration(
        generation: Long,
        messageId: String,
    ) {
        synchronized(lock) {
            val current = registrationProbe
            if (
                activeGeneration == generation &&
                current?.generation == generation &&
                current.messageId == messageId
            ) {
                registrationProbe = null
            }
        }
    }

    fun acceptRegistration(
        generation: Long,
        correlationId: String?,
        serverTimeMs: Long,
    ): CoreClockSyncOutcome {
        val receivedAt = monotonicMillis().coerceAtLeast(0)
        val receivedWall = wallClockMillis().coerceAtLeast(0)
        val acceptedProbe = synchronized(lock) {
            if (activeGeneration != generation) {
                return inactiveGenerationOutcome()
            }
            val estimatorGeneration = activeEstimatorGeneration
                ?: return inactiveGenerationOutcome()
            val current = registrationProbe
                ?: return CoreClockSyncOutcome(
                    accepted = false,
                    fatal = true,
                    failureKind = CoreClockSyncFailureKind.UNKNOWN_PROBE,
                    detail = "device.registered arrived without an active registration probe",
                )
            if (correlationId == null || correlationId != current.messageId) {
                return CoreClockSyncOutcome(
                    accepted = false,
                    fatal = true,
                    failureKind = CoreClockSyncFailureKind.INVALID_IDENTITY,
                    detail = "device.registered correlation_id did not match registration message_id",
                )
            }
            registrationProbe = null
            AcceptedProbe(
                estimatorGeneration = estimatorGeneration,
                sentAtElapsedMs = current.sentAtElapsedMs,
            )
        }
        return sampleOutcome(
            estimatorGeneration = acceptedProbe.estimatorGeneration,
            probeSentAtElapsedMs = acceptedProbe.sentAtElapsedMs,
            receivedAtElapsedMs = receivedAt,
            serverTimeMs = serverTimeMs,
            receivedWallClockMs = receivedWall,
            source = "registration",
        )
    }

    fun markHeartbeatSent(
        generation: Long,
        messageId: String,
        sequence: Long,
    ): Boolean {
        if (!isUuid(messageId) || sequence < 0) {
            return false
        }
        val sentAt = monotonicMillis().coerceAtLeast(0)
        return synchronized(lock) {
            if (activeGeneration != generation || activeEstimatorGeneration == null) {
                return@synchronized false
            }
            heartbeatProbes[messageId] = HeartbeatProbe(
                sequence = sequence,
                sentAtElapsedMs = sentAt,
            )
            while (heartbeatProbes.size > maxPendingHeartbeatProbes) {
                val iterator = heartbeatProbes.entries.iterator()
                if (!iterator.hasNext()) {
                    break
                }
                iterator.next()
                iterator.remove()
            }
            true
        }
    }

    fun discardHeartbeat(
        generation: Long,
        messageId: String,
    ) {
        synchronized(lock) {
            if (activeGeneration != generation) {
                return
            }
            heartbeatProbes.remove(messageId)
        }
    }

    fun acceptHeartbeat(
        generation: Long,
        correlationId: String?,
        sequence: Long,
        serverTimeMs: Long,
    ): CoreClockSyncOutcome {
        val receivedAt = monotonicMillis().coerceAtLeast(0)
        val receivedWall = wallClockMillis().coerceAtLeast(0)
        val acceptedProbe = synchronized(lock) {
            if (activeGeneration != generation) {
                return inactiveGenerationOutcome()
            }
            val estimatorGeneration = activeEstimatorGeneration
                ?: return inactiveGenerationOutcome()
            if (correlationId == null || !isUuid(correlationId)) {
                return CoreClockSyncOutcome(
                    accepted = false,
                    fatal = true,
                    failureKind = CoreClockSyncFailureKind.INVALID_IDENTITY,
                    detail = "heartbeat_ack requires a UUID correlation_id",
                )
            }
            val current = heartbeatProbes.remove(correlationId)
                ?: return CoreClockSyncOutcome(
                    accepted = false,
                    fatal = false,
                    failureKind = CoreClockSyncFailureKind.UNKNOWN_PROBE,
                    reading = estimator.reading(),
                    detail = "late or unknown heartbeat_ack probe was ignored",
                )
            if (current.sequence != sequence) {
                return CoreClockSyncOutcome(
                    accepted = false,
                    fatal = true,
                    failureKind = CoreClockSyncFailureKind.SEQUENCE_MISMATCH,
                    reading = estimator.reading(),
                    detail = "heartbeat_ack sequence did not match its correlated probe",
                )
            }
            AcceptedProbe(
                estimatorGeneration = estimatorGeneration,
                sentAtElapsedMs = current.sentAtElapsedMs,
            )
        }
        return sampleOutcome(
            estimatorGeneration = acceptedProbe.estimatorGeneration,
            probeSentAtElapsedMs = acceptedProbe.sentAtElapsedMs,
            receivedAtElapsedMs = receivedAt,
            serverTimeMs = serverTimeMs,
            receivedWallClockMs = receivedWall,
            source = "heartbeat",
        )
    }

    fun reading(): CoreClockReading? = estimator.reading()

    private fun sampleOutcome(
        estimatorGeneration: Long,
        probeSentAtElapsedMs: Long,
        receivedAtElapsedMs: Long,
        serverTimeMs: Long,
        receivedWallClockMs: Long,
        source: String,
    ): CoreClockSyncOutcome {
        val sample = estimator.recordSample(
            sampleGeneration = estimatorGeneration,
            requestSentElapsedMs = probeSentAtElapsedMs,
            responseReceivedElapsedMs = receivedAtElapsedMs,
            serverTimeMs = serverTimeMs,
            responseReceivedWallClockMs = receivedWallClockMs,
        )
        if (!sample.accepted) {
            return CoreClockSyncOutcome(
                accepted = false,
                fatal = true,
                failureKind = CoreClockSyncFailureKind.SAMPLE_REJECTED,
                reading = sample.reading,
                detail = "$source Core clock sample was rejected: ${sample.detail}",
            )
        }
        return CoreClockSyncOutcome(
            accepted = true,
            fatal = false,
            reading = sample.reading,
            wallClockJumpDetected = sample.wallClockJumpDetected,
            coreDiscontinuityDetected = sample.coreDiscontinuityDetected,
            detail = "$source Core clock sample accepted: ${sample.detail}",
        )
    }

    private fun inactiveGenerationOutcome(): CoreClockSyncOutcome = CoreClockSyncOutcome(
        accepted = false,
        fatal = false,
        failureKind = CoreClockSyncFailureKind.INACTIVE_GENERATION,
        reading = estimator.reading(),
        detail = "clock message belongs to an inactive WebSocket generation",
    )

    private data class RegistrationProbe(
        val generation: Long,
        val messageId: String,
        val sentAtElapsedMs: Long,
    )

    private data class HeartbeatProbe(
        val sequence: Long,
        val sentAtElapsedMs: Long,
    )

    private data class AcceptedProbe(
        val estimatorGeneration: Long,
        val sentAtElapsedMs: Long,
    )

    private companion object {
        const val DEFAULT_MAX_PENDING_HEARTBEAT_PROBES: Int = 32

        fun isUuid(value: String): Boolean = runCatching {
            UUID.fromString(value)
        }.isSuccess
    }
}

private object CoreClockGenerationSequence {
    private val value = AtomicLong(0)

    fun next(): Long {
        while (true) {
            val current = value.get()
            val next = if (current == Long.MAX_VALUE) 1 else current + 1
            if (value.compareAndSet(current, next)) {
                return next
            }
        }
    }
}
