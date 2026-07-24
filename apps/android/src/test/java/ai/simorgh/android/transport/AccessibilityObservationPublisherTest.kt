package ai.simorgh.android.transport

import ai.simorgh.android.accessibility.AccessibilityNodeSnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.accessibility.ScreenBounds
import ai.simorgh.android.protocol.DeviceObservationAckPayload
import ai.simorgh.android.protocol.ObservationAckStatus
import ai.simorgh.android.protocol.ProtocolEnvelope
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.PriorityQueue

class AccessibilityObservationPublisherTest {
    @Test
    fun `latest snapshot replaces older pending state`() {
        val scheduler = ManualObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val publisher = publisher(scheduler, sent)
        val oldSnapshot = snapshot(id = "11111111-1111-1111-1111-111111111111", text = "قدیمی")
        val latestSnapshot = snapshot(id = "22222222-2222-2222-2222-222222222222", text = "جدید")

        assertTrue(publisher.submit(oldSnapshot))
        assertTrue(publisher.submit(latestSnapshot))
        assertEquals(latestSnapshot.snapshotId, publisher.pendingSnapshotId())

        publisher.setConnected(true)
        scheduler.runCurrent()

        assertEquals(1, sent.size)
        assertEquals(latestSnapshot.snapshotId, publisher.inFlightSnapshotId())
        publisher.close()
    }

    @Test
    fun `acknowledged state is deduplicated even with a new snapshot id`() {
        val scheduler = ManualObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val publisher = publisher(scheduler, sent)
        val first = snapshot(id = "11111111-1111-1111-1111-111111111111", text = "سلام")
        val sameState = first.copy(
            snapshotId = "22222222-2222-2222-2222-222222222222",
            capturedAtMs = first.capturedAtMs + 1_000,
        )

        publisher.setConnected(true)
        assertTrue(publisher.submit(first))
        scheduler.runCurrent()
        val envelope = sent.single()

        assertTrue(
            publisher.acknowledge(
                acknowledgement = DeviceObservationAckPayload(
                    snapshotId = first.snapshotId,
                    status = ObservationAckStatus.ACCEPTED,
                    receivedAtMs = 10,
                ),
                correlationId = envelope.messageId,
            ),
        )
        assertFalse(publisher.submit(sameState))
        assertNull(publisher.pendingSnapshotId())
        publisher.close()
    }

    @Test
    fun `ack timeout retries the exact same envelope and stops after max attempts`() {
        val scheduler = ManualObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val events = mutableListOf<String>()
        val publisher = AccessibilityObservationPublisher(
            deviceId = DEVICE_ID,
            sender = { envelope -> sent += envelope; true },
            listener = events::add,
            scheduler = scheduler,
            minimumSendIntervalMillis = 0,
            acknowledgementTimeoutMillis = 100,
            maxAttempts = 3,
        )
        val snapshot = snapshot(id = "11111111-1111-1111-1111-111111111111", text = "retry")

        publisher.setConnected(true)
        publisher.submit(snapshot)
        scheduler.runCurrent()
        scheduler.advanceBy(100)
        scheduler.advanceBy(100)
        scheduler.advanceBy(100)

        assertEquals(3, sent.size)
        assertEquals(1, sent.map(ProtocolEnvelope::messageId).distinct().size)
        assertNull(publisher.inFlightSnapshotId())
        assertTrue(events.last().contains("failed after 3 attempts"))
        publisher.close()
    }

    @Test
    fun `minimum interval delays the next accepted state`() {
        val scheduler = ManualObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val publisher = publisher(scheduler, sent, minimumIntervalMillis = 500)
        val first = snapshot(id = "11111111-1111-1111-1111-111111111111", text = "اول")
        val second = snapshot(id = "22222222-2222-2222-2222-222222222222", text = "دوم")

        publisher.setConnected(true)
        publisher.submit(first)
        scheduler.runCurrent()
        val firstEnvelope = sent.single()
        publisher.acknowledge(
            acknowledgement = DeviceObservationAckPayload(
                snapshotId = first.snapshotId,
                status = ObservationAckStatus.ACCEPTED,
                receivedAtMs = 1,
            ),
            correlationId = firstEnvelope.messageId,
        )
        publisher.submit(second)

        scheduler.advanceBy(499)
        assertEquals(1, sent.size)
        scheduler.advanceBy(1)
        assertEquals(2, sent.size)
        publisher.close()
    }

    @Test
    fun `fingerprint ignores capture identity but includes checked state`() {
        val first = snapshot(id = "11111111-1111-1111-1111-111111111111", text = "گزینه")
        val sameState = first.copy(
            snapshotId = "22222222-2222-2222-2222-222222222222",
            capturedAtMs = 99_999,
        )
        val changed = sameState.copy(
            nodes = sameState.nodes.map { node -> node.copy(checked = true) },
        )

        assertEquals(
            AccessibilitySnapshotFingerprint.calculate(first),
            AccessibilitySnapshotFingerprint.calculate(sameState),
        )
        assertNotEquals(
            AccessibilitySnapshotFingerprint.calculate(first),
            AccessibilitySnapshotFingerprint.calculate(changed),
        )
    }

    private fun publisher(
        scheduler: ManualObservationScheduler,
        sent: MutableList<ProtocolEnvelope>,
        minimumIntervalMillis: Long = 0,
    ): AccessibilityObservationPublisher = AccessibilityObservationPublisher(
        deviceId = DEVICE_ID,
        sender = { envelope -> sent += envelope; true },
        scheduler = scheduler,
        minimumSendIntervalMillis = minimumIntervalMillis,
        acknowledgementTimeoutMillis = 10_000,
        maxAttempts = 3,
    )

    private fun snapshot(id: String, text: String): AccessibilitySnapshot = AccessibilitySnapshot(
        snapshotId = id,
        capturedAtMs = 1_000,
        triggeringEventType = 32,
        activePackage = "com.example",
        activeWindowId = 1,
        rootNodeId = "root",
        windows = emptyList(),
        nodes = listOf(
            AccessibilityNodeSnapshot(
                nodeId = "root",
                path = "0",
                depth = 0,
                windowId = 1,
                packageName = "com.example",
                className = "android.widget.CheckBox",
                text = text,
                bounds = ScreenBounds(0, 0, 100, 100),
                semanticFingerprint = "semantic-$text",
                childCount = 0,
                inputType = 0,
                clickable = true,
                longClickable = false,
                focusable = true,
                focused = false,
                editable = false,
                scrollable = false,
                enabled = true,
                selected = false,
                checkable = true,
                checked = false,
                visibleToUser = true,
                accessibilityFocused = false,
                password = false,
                heading = false,
                actions = emptyList(),
            ),
        ),
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

        fun advanceBy(milliseconds: Long) {
            require(milliseconds >= 0)
            runUntil(currentTimeMillis + milliseconds)
        }

        private fun runUntil(targetTimeMillis: Long) {
            while (true) {
                val next = tasks.peek() ?: break
                if (next.dueAtMillis > targetTimeMillis) {
                    break
                }
                tasks.remove()
                currentTimeMillis = next.dueAtMillis
                if (!next.cancelled) {
                    next.action()
                }
            }
            currentTimeMillis = targetTimeMillis
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
    }
}
