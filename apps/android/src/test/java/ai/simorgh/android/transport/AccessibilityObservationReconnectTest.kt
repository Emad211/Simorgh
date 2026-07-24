package ai.simorgh.android.transport

import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.protocol.DeviceObservationAckPayload
import ai.simorgh.android.protocol.DeviceObservationPayload
import ai.simorgh.android.protocol.DeviceProtocol
import ai.simorgh.android.protocol.ObservationAckStatus
import ai.simorgh.android.protocol.ProtocolEnvelope
import kotlinx.serialization.json.decodeFromJsonElement
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.PriorityQueue
import java.util.concurrent.atomic.AtomicInteger

class AccessibilityObservationReconnectTest {
    @Test
    fun `new registered connection invalidates old evidence and resends current state`() {
        val scheduler = ManualScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val invalidations = AtomicInteger(0)
        val publisher = AccessibilityObservationPublisher(
            deviceId = DEVICE_ID,
            sender = { envelope ->
                sent += envelope
                true
            },
            acknowledgementInvalidator = { invalidations.incrementAndGet() },
            scheduler = scheduler,
            minimumSendIntervalMillis = 0,
            acknowledgementTimeoutMillis = 1_000,
            streamId = STREAM_ID,
        )
        val snapshot = AccessibilitySnapshot(
            snapshotId = SNAPSHOT_ID,
            capturedAtMs = 1_000,
            activePackage = "com.example",
            windows = emptyList(),
            nodes = emptyList(),
            truncated = false,
            truncationReasons = emptyList(),
            maxDepthObserved = 0,
        )

        publisher.setConnected(true)
        assertTrue(publisher.submit(snapshot))
        scheduler.runCurrent()
        val firstEnvelope = sent.single()
        val firstPayload = payload(firstEnvelope)
        assertTrue(
            publisher.acknowledge(
                acknowledgement = DeviceObservationAckPayload(
                    streamId = firstPayload.streamId,
                    sequence = firstPayload.sequence,
                    snapshotId = firstPayload.snapshot.snapshotId,
                    status = ObservationAckStatus.ACCEPTED,
                    receivedAtMs = 1_100,
                ),
                correlationId = firstEnvelope.messageId,
            ),
        )

        publisher.setConnected(false)
        assertEquals(1, invalidations.get())
        publisher.setConnected(true)
        scheduler.runCurrent()

        assertEquals(2, sent.size)
        val secondEnvelope = sent.last()
        val secondPayload = payload(secondEnvelope)
        assertNotEquals(firstEnvelope.messageId, secondEnvelope.messageId)
        assertEquals(firstPayload.sequence + 1, secondPayload.sequence)
        assertEquals(firstPayload.snapshot, secondPayload.snapshot)
        assertEquals(firstPayload.stateFingerprint, secondPayload.stateFingerprint)

        publisher.close()
        assertEquals(2, invalidations.get())
    }

    private fun payload(envelope: ProtocolEnvelope): DeviceObservationPayload =
        DeviceProtocol.json.decodeFromJsonElement(envelope.payload)

    private class ManualScheduler : ObservationScheduler {
        private val tasks = PriorityQueue<ScheduledTask>(
            compareBy<ScheduledTask> { it.dueAtMillis }.thenBy { it.sequence },
        )
        private var currentTimeMillis = 0L
        private var nextSequence = 0L

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
        const val DEVICE_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        const val STREAM_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        const val SNAPSHOT_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    }
}
