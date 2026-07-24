package ai.simorgh.android.transport

import ai.simorgh.android.accessibility.AccessibilityObservationBus
import ai.simorgh.android.accessibility.AccessibilityObserverState
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.protocol.DeviceObservationRefreshPayload
import ai.simorgh.android.protocol.ObservationRefreshAckStatus
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.PriorityQueue

class AccessibilityRefreshCoordinatorRaceTest {
    @Before
    fun setUp() {
        AccessibilityObservationBus.clearForTest()
    }

    @After
    fun tearDown() {
        AccessibilityObservationBus.clearForTest()
    }

    @Test
    fun `same request remains duplicate while captured snapshot is being projected`() {
        val publisher = publisher()
        val terminal = mutableListOf<TerminalAck>()
        val baseline = snapshot(BASELINE_SNAPSHOT_ID, 1_000)
        AccessibilityObservationBus.publish(
            AccessibilityObserverState(
                serviceConnected = true,
                latestSnapshot = baseline,
            ),
        )

        lateinit var coordinator: AccessibilityRefreshCoordinator
        var duplicate: ObservationRefreshReceipt? = null
        coordinator = coordinator(
            publisher = publisher,
            terminal = terminal,
            snapshotProjector = { captured ->
                duplicate = coordinator.receive(REQUEST_ID, request())
                captured
            },
        )

        try {
            assertEquals(
                ObservationRefreshAckStatus.ACCEPTED,
                coordinator.receive(REQUEST_ID, request()).status,
            )

            AccessibilityObservationBus.publish(
                AccessibilityObserverState(
                    serviceConnected = true,
                    latestSnapshot = snapshot(NEW_SNAPSHOT_ID, 1_100),
                ),
            )

            assertEquals(ObservationRefreshAckStatus.DUPLICATE, duplicate?.status)
            assertEquals(REQUEST_ID, publisher.pendingRefreshRequestId())
            assertTrue(terminal.isEmpty())
        } finally {
            coordinator.close()
            publisher.close()
        }
    }

    @Test
    fun `observer disconnect after capture does not invalidate submitting evidence`() {
        val publisher = publisher()
        val terminal = mutableListOf<TerminalAck>()
        AccessibilityObservationBus.publish(
            AccessibilityObserverState(
                serviceConnected = true,
                latestSnapshot = snapshot(BASELINE_SNAPSHOT_ID, 1_000),
            ),
        )
        val coordinator = coordinator(
            publisher = publisher,
            terminal = terminal,
            snapshotProjector = { captured ->
                AccessibilityObservationBus.publish(
                    AccessibilityObserverState(serviceConnected = false),
                )
                captured
            },
        )

        try {
            assertEquals(
                ObservationRefreshAckStatus.ACCEPTED,
                coordinator.receive(REQUEST_ID, request()).status,
            )

            AccessibilityObservationBus.publish(
                AccessibilityObserverState(
                    serviceConnected = true,
                    latestSnapshot = snapshot(NEW_SNAPSHOT_ID, 1_100),
                ),
            )

            assertEquals(REQUEST_ID, publisher.pendingRefreshRequestId())
            assertTrue(terminal.isEmpty())
        } finally {
            coordinator.close()
            publisher.close()
        }
    }

    @Test
    fun `synchronous capture progress wins over requester false return`() {
        val publisher = publisher()
        val terminal = mutableListOf<TerminalAck>()
        AccessibilityObservationBus.publish(
            AccessibilityObserverState(
                serviceConnected = true,
                latestSnapshot = snapshot(BASELINE_SNAPSHOT_ID, 1_000),
            ),
        )
        val coordinator = coordinator(
            publisher = publisher,
            terminal = terminal,
            captureRequester = {
                AccessibilityObservationBus.publish(
                    AccessibilityObserverState(
                        serviceConnected = true,
                        latestSnapshot = snapshot(NEW_SNAPSHOT_ID, 1_100),
                    ),
                )
                false
            },
        )

        try {
            val receipt = coordinator.receive(REQUEST_ID, request())

            assertEquals(ObservationRefreshAckStatus.DUPLICATE, receipt.status)
            assertEquals(REQUEST_ID, publisher.pendingRefreshRequestId())
            assertTrue(terminal.isEmpty())
        } finally {
            coordinator.close()
            publisher.close()
        }
    }

    private fun coordinator(
        publisher: AccessibilityObservationPublisher,
        terminal: MutableList<TerminalAck>,
        snapshotProjector: (AccessibilitySnapshot) -> AccessibilitySnapshot = { it },
        captureRequester: () -> Boolean = { true },
    ): AccessibilityRefreshCoordinator = AccessibilityRefreshCoordinator(
        publisher = publisher,
        snapshotProjector = snapshotProjector,
        captureRequester = captureRequester,
        terminalAcknowledgementEmitter = { requestId, status, detail ->
            terminal += TerminalAck(requestId, status, detail)
        },
        scheduler = ManualObservationScheduler(),
    )

    private fun publisher(): AccessibilityObservationPublisher =
        AccessibilityObservationPublisher(
            deviceId = DEVICE_ID,
            sender = { true },
            scheduler = ManualObservationScheduler(),
            minimumSendIntervalMillis = 0,
            acknowledgementTimeoutMillis = 1_000,
            streamId = STREAM_ID,
        )

    private fun request(): DeviceObservationRefreshPayload =
        DeviceObservationRefreshPayload(
            requestId = REQUEST_ID,
            timeoutMs = 5_000,
            reason = "race fixture",
        )

    private fun snapshot(snapshotId: String, capturedAtMs: Long): AccessibilitySnapshot =
        AccessibilitySnapshot(
            snapshotId = snapshotId,
            capturedAtMs = capturedAtMs,
            activePackage = "com.example",
            activeWindowId = null,
            rootNodeId = null,
            windows = emptyList(),
            nodes = emptyList(),
            truncated = false,
            truncationReasons = emptyList(),
            maxDepthObserved = 0,
        )

    private data class TerminalAck(
        val requestId: String,
        val status: ObservationRefreshAckStatus,
        val detail: String,
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
        const val REQUEST_ID = "33333333-3333-3333-3333-333333333333"
        const val BASELINE_SNAPSHOT_ID = "44444444-4444-4444-4444-444444444444"
        const val NEW_SNAPSHOT_ID = "55555555-5555-5555-5555-555555555555"
    }
}
