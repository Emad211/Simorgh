package ai.simorgh.android.transport

import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.protocol.DeviceObservationAckPayload
import ai.simorgh.android.protocol.DeviceObservationPayload
import ai.simorgh.android.protocol.DeviceProtocol
import ai.simorgh.android.protocol.ObservationAckStatus
import ai.simorgh.android.protocol.ProtocolEnvelope
import kotlinx.serialization.json.decodeFromJsonElement
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.PriorityQueue

class AccessibilityObservationRefreshPublisherTest {
    @Test
    fun `refresh bypasses unchanged-state deduplication`() {
        val scheduler = ManualObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val publisher = publisher(scheduler = scheduler, sent = sent)
        val first = snapshot(FIRST_SNAPSHOT_ID, 1_000, "com.example")
        val refreshed = snapshot(REFRESHED_SNAPSHOT_ID, 2_000, "com.example")

        publisher.setConnected(true)
        assertTrue(publisher.submit(first))
        scheduler.runCurrent()
        acknowledgeLast(publisher, sent)

        assertFalse(publisher.submit(refreshed))
        assertEquals(
            RefreshObservationSubmissionStatus.ACCEPTED,
            publisher.submitRefresh(refreshed, REFRESH_REQUEST_ID),
        )
        scheduler.runCurrent()

        assertEquals(2, sent.size)
        val forced = sent.last()
        val payload = DeviceProtocol.json.decodeFromJsonElement<DeviceObservationPayload>(
            forced.payload,
        )
        assertEquals(DeviceProtocol.TYPE_OBSERVATION, forced.type)
        assertEquals(REFRESH_REQUEST_ID, forced.correlationId)
        assertEquals(REFRESHED_SNAPSHOT_ID, payload.snapshot.snapshotId)
        assertEquals(1, payload.sequence)

        acknowledgeLast(
            publisher = publisher,
            sent = sent,
            status = ObservationAckStatus.UNCHANGED,
        )
        assertTrue(publisher.hasRefreshRequest(REFRESH_REQUEST_ID))
        publisher.close()
    }

    @Test
    fun `refresh waits for normal in-flight delivery and then has priority`() {
        val scheduler = ManualObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val publisher = publisher(scheduler = scheduler, sent = sent)

        publisher.setConnected(true)
        assertTrue(
            publisher.submit(
                snapshot(FIRST_SNAPSHOT_ID, 1_000, "com.first"),
            ),
        )
        scheduler.runCurrent()
        assertEquals(1, sent.size)

        assertTrue(
            publisher.submit(
                snapshot(PENDING_NORMAL_SNAPSHOT_ID, 1_100, "com.pending"),
            ),
        )
        assertEquals(
            RefreshObservationSubmissionStatus.ACCEPTED,
            publisher.submitRefresh(
                snapshot(REFRESHED_SNAPSHOT_ID, 1_200, "com.refresh"),
                REFRESH_REQUEST_ID,
            ),
        )

        acknowledgeLast(publisher, sent)
        scheduler.runCurrent()

        assertEquals(2, sent.size)
        assertEquals(REFRESH_REQUEST_ID, sent.last().correlationId)
        val payload = DeviceProtocol.json.decodeFromJsonElement<DeviceObservationPayload>(
            sent.last().payload,
        )
        assertEquals(REFRESHED_SNAPSHOT_ID, payload.snapshot.snapshotId)
        publisher.close()
    }

    @Test
    fun `refresh retry preserves exact envelope identity`() {
        val scheduler = ManualObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val publisher = AccessibilityObservationPublisher(
            deviceId = DEVICE_ID,
            sender = { envelope -> sent += envelope; true },
            scheduler = scheduler,
            minimumSendIntervalMillis = 0,
            acknowledgementTimeoutMillis = 100,
            maxAttempts = 3,
            streamId = STREAM_ID,
        )

        publisher.setConnected(true)
        assertEquals(
            RefreshObservationSubmissionStatus.ACCEPTED,
            publisher.submitRefresh(
                snapshot(REFRESHED_SNAPSHOT_ID, 1_000, "com.example"),
                REFRESH_REQUEST_ID,
            ),
        )
        scheduler.runCurrent()
        val first = sent.single()

        scheduler.advanceBy(100)
        val second = sent.last()

        assertEquals(2, sent.size)
        assertEquals(first.messageId, second.messageId)
        assertEquals(first.correlationId, second.correlationId)
        assertEquals(first.payload, second.payload)
        publisher.close()
    }

    @Test
    fun `duplicate refresh and competing refresh are distinguished`() {
        val scheduler = ManualObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val publisher = publisher(scheduler = scheduler, sent = sent)
        val snapshot = snapshot(REFRESHED_SNAPSHOT_ID, 1_000, "com.example")

        assertEquals(
            RefreshObservationSubmissionStatus.ACCEPTED,
            publisher.submitRefresh(snapshot, REFRESH_REQUEST_ID),
        )
        assertEquals(
            RefreshObservationSubmissionStatus.DUPLICATE,
            publisher.submitRefresh(snapshot, REFRESH_REQUEST_ID),
        )
        assertEquals(
            RefreshObservationSubmissionStatus.BUSY,
            publisher.submitRefresh(snapshot, OTHER_REFRESH_REQUEST_ID),
        )
        publisher.close()
    }

    private fun publisher(
        scheduler: ManualObservationScheduler,
        sent: MutableList<ProtocolEnvelope>,
    ): AccessibilityObservationPublisher = AccessibilityObservationPublisher(
        deviceId = DEVICE_ID,
        sender = { envelope -> sent += envelope; true },
        scheduler = scheduler,
        minimumSendIntervalMillis = 0,
        acknowledgementTimeoutMillis = 1_000,
        streamId = STREAM_ID,
    )

    private fun acknowledgeLast(
        publisher: AccessibilityObservationPublisher,
        sent: List<ProtocolEnvelope>,
        status: ObservationAckStatus = ObservationAckStatus.ACCEPTED,
    ) {
        val envelope = sent.last()
        val payload = DeviceProtocol.json.decodeFromJsonElement<DeviceObservationPayload>(
            envelope.payload,
        )
        assertTrue(
            publisher.acknowledge(
                acknowledgement = DeviceObservationAckPayload(
                    streamId = payload.streamId,
                    sequence = payload.sequence,
                    snapshotId = payload.snapshot.snapshotId,
                    status = status,
                    receivedAtMs = 5_000,
                ),
                correlationId = envelope.messageId,
            ),
        )
    }

    private fun snapshot(
        snapshotId: String,
        capturedAtMs: Long,
        activePackage: String,
    ): AccessibilitySnapshot = AccessibilitySnapshot(
        snapshotId = snapshotId,
        capturedAtMs = capturedAtMs,
        activePackage = activePackage,
        activeWindowId = null,
        rootNodeId = null,
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
            runUntil(currentTimeMillis)
        }

        fun advanceBy(durationMillis: Long) {
            currentTimeMillis += durationMillis
            runUntil(currentTimeMillis)
        }

        private fun runUntil(targetMillis: Long) {
            while (true) {
                val next = tasks.peek() ?: break
                if (next.dueAtMillis > targetMillis) {
                    break
                }
                tasks.remove()
                currentTimeMillis = next.dueAtMillis
                if (!next.cancelled) {
                    next.action()
                }
            }
            currentTimeMillis = targetMillis
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
        const val STREAM_ID = "22222222-2222-2222-2222-222222222222"
        const val REFRESH_REQUEST_ID = "33333333-3333-3333-3333-333333333333"
        const val OTHER_REFRESH_REQUEST_ID = "44444444-4444-4444-4444-444444444444"
        const val FIRST_SNAPSHOT_ID = "55555555-5555-5555-5555-555555555555"
        const val REFRESHED_SNAPSHOT_ID = "66666666-6666-6666-6666-666666666666"
        const val PENDING_NORMAL_SNAPSHOT_ID = "77777777-7777-7777-7777-777777777777"
    }
}
