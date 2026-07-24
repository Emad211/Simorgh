package ai.simorgh.android.transport

import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AcknowledgedAccessibilityObservation
import ai.simorgh.android.protocol.DeviceObservationAckPayload
import ai.simorgh.android.protocol.DeviceObservationPayload
import ai.simorgh.android.protocol.DeviceProtocol
import ai.simorgh.android.protocol.ObservationAckStatus
import ai.simorgh.android.protocol.ProtocolEnvelope
import kotlinx.serialization.json.decodeFromJsonElement
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.PriorityQueue

class AccessibilityObservationAcknowledgementTest {
    @Test
    fun `accepted observation exposes compact Core-acknowledged evidence`() {
        val scheduler = ManualObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val acknowledged = mutableListOf<AcknowledgedAccessibilityObservation>()
        val publisher = AccessibilityObservationPublisher(
            deviceId = DEVICE_ID,
            sender = { envelope -> sent += envelope; true },
            acknowledgementListener = acknowledged::add,
            scheduler = scheduler,
            minimumSendIntervalMillis = 0,
            acknowledgementTimeoutMillis = 1_000,
        )
        val snapshot = snapshot(SNAPSHOT_ID)

        publisher.setConnected(true)
        assertTrue(publisher.submit(snapshot))
        scheduler.runCurrent()
        val envelope = sent.single()
        val payload = DeviceProtocol.json.decodeFromJsonElement<DeviceObservationPayload>(
            envelope.payload,
        )
        assertTrue(
            publisher.acknowledge(
                acknowledgement = DeviceObservationAckPayload(
                    streamId = payload.streamId,
                    sequence = payload.sequence,
                    snapshotId = snapshot.snapshotId,
                    status = ObservationAckStatus.ACCEPTED,
                    receivedAtMs = 2_000,
                ),
                correlationId = envelope.messageId,
            ),
        )

        val evidence = acknowledged.single()
        assertEquals(payload.streamId, evidence.streamId)
        assertEquals(payload.sequence, evidence.sequence)
        assertEquals(payload.stateFingerprint, evidence.stateFingerprint)
        assertEquals(snapshot.snapshotId, evidence.snapshotId)
        assertEquals(snapshot.capturedAtMs, evidence.capturedAtMs)
        assertEquals(snapshot.activePackage, evidence.activePackage)
        assertEquals(2_000, evidence.acknowledgedAtMs)
        publisher.close()
    }

    @Test
    fun `stale acknowledgement never becomes executable evidence`() {
        val scheduler = ManualObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val acknowledged = mutableListOf<AcknowledgedAccessibilityObservation>()
        val publisher = AccessibilityObservationPublisher(
            deviceId = DEVICE_ID,
            sender = { envelope -> sent += envelope; true },
            acknowledgementListener = acknowledged::add,
            scheduler = scheduler,
            minimumSendIntervalMillis = 0,
            acknowledgementTimeoutMillis = 1_000,
        )
        val snapshot = snapshot(STALE_SNAPSHOT_ID)

        publisher.setConnected(true)
        publisher.submit(snapshot)
        scheduler.runCurrent()
        val envelope = sent.single()
        val payload = DeviceProtocol.json.decodeFromJsonElement<DeviceObservationPayload>(
            envelope.payload,
        )
        assertTrue(
            publisher.acknowledge(
                acknowledgement = DeviceObservationAckPayload(
                    streamId = payload.streamId,
                    sequence = payload.sequence,
                    snapshotId = snapshot.snapshotId,
                    status = ObservationAckStatus.STALE,
                    receivedAtMs = 3_000,
                ),
                correlationId = envelope.messageId,
            ),
        )

        assertTrue(acknowledged.isEmpty())
        publisher.close()
    }

    private fun snapshot(id: String): AccessibilitySnapshot = AccessibilitySnapshot(
        snapshotId = id,
        capturedAtMs = 1_000,
        activePackage = "com.example",
        activeWindowId = 1,
        windows = emptyList(),
        nodes = emptyList(),
        truncated = false,
        truncationReasons = emptyList(),
        maxDepthObserved = 0,
    )

    private class ManualObservationScheduler : ObservationScheduler {
        private val tasks = PriorityQueue<ScheduledTask>(
            compareBy<ScheduledTask> { it.dueAtMillis }.thenBy { it.sequence },
        )
        private var nextSequence = 0L
        private var currentTimeMillis = 0L

        override fun nowMillis(): Long = currentTimeMillis

        override fun schedule(delayMillis: Long, task: () -> Unit): ScheduledObservationTask {
            val scheduled = ScheduledTask(
                dueAtMillis = currentTimeMillis + delayMillis.coerceAtLeast(0),
                sequence = nextSequence++,
                action = task,
            )
            tasks += scheduled
            return ScheduledObservationTask { scheduled.cancelled = true }
        }

        fun runCurrent() {
            while (true) {
                val next = tasks.peek() ?: break
                if (next.dueAtMillis > currentTimeMillis) {
                    break
                }
                tasks.remove()
                if (!next.cancelled) {
                    next.action()
                }
            }
        }

        override fun close() {
            tasks.clear()
        }

        private data class ScheduledTask(
            val dueAtMillis: Long,
            val sequence: Long,
            val action: () -> Unit,
            var cancelled: Boolean = false,
        )
    }

    private companion object {
        const val DEVICE_ID = "11111111-1111-1111-1111-111111111111"
        const val SNAPSHOT_ID = "22222222-2222-2222-2222-222222222222"
        const val STALE_SNAPSHOT_ID = "33333333-3333-3333-3333-333333333333"
    }
}
