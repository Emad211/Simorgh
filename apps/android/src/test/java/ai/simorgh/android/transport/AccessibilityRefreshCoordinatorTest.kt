package ai.simorgh.android.transport

import ai.simorgh.android.accessibility.AccessibilityObservationBus
import ai.simorgh.android.accessibility.AccessibilityObserverState
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.protocol.DeviceObservationRefreshPayload
import ai.simorgh.android.protocol.ObservationRefreshAckStatus
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.PriorityQueue
import java.util.concurrent.atomic.AtomicInteger

class AccessibilityRefreshCoordinatorTest {
    @Before
    fun setUp() {
        AccessibilityObservationBus.clearForTest()
    }

    @After
    fun tearDown() {
        AccessibilityObservationBus.clearForTest()
    }

    @Test
    fun `accepted request waits for a new snapshot id before publisher submission`() {
        val publisherScheduler = ManualObservationScheduler()
        val coordinatorScheduler = ManualObservationScheduler()
        val publisher = publisher(publisherScheduler)
        val captures = AtomicInteger(0)
        val terminal = mutableListOf<TerminalAck>()
        val baseline = snapshot(BASELINE_SNAPSHOT_ID, 1_000, "com.example")
        AccessibilityObservationBus.publish(
            AccessibilityObserverState(
                serviceConnected = true,
                latestSnapshot = baseline,
            ),
        )
        val coordinator = coordinator(
            publisher = publisher,
            scheduler = coordinatorScheduler,
            captureRequester = { captures.incrementAndGet(); true },
            terminal = terminal,
        )

        try {
            val receipt = coordinator.receive(REQUEST_ID, request(REQUEST_ID))
            assertEquals(ObservationRefreshAckStatus.ACCEPTED, receipt.status)
            assertEquals(1, captures.get())
            assertNull(publisher.pendingRefreshRequestId())

            AccessibilityObservationBus.publish(
                AccessibilityObserverState(
                    serviceConnected = true,
                    latestSnapshot = baseline,
                ),
            )
            assertNull(publisher.pendingRefreshRequestId())

            AccessibilityObservationBus.publish(
                AccessibilityObserverState(
                    serviceConnected = true,
                    latestSnapshot = snapshot(NEW_SNAPSHOT_ID, 1_100, "com.example"),
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
    fun `same request is duplicate while competing request is busy`() {
        val publisher = publisher(ManualObservationScheduler())
        val coordinator = connectedCoordinator(publisher = publisher)

        try {
            assertEquals(
                ObservationRefreshAckStatus.ACCEPTED,
                coordinator.receive(REQUEST_ID, request(REQUEST_ID)).status,
            )
            assertEquals(
                ObservationRefreshAckStatus.DUPLICATE,
                coordinator.receive(REQUEST_ID, request(REQUEST_ID)).status,
            )
            assertEquals(
                ObservationRefreshAckStatus.BUSY,
                coordinator.receive(OTHER_REQUEST_ID, request(OTHER_REQUEST_ID)).status,
            )
        } finally {
            coordinator.close()
            publisher.close()
        }
    }

    @Test
    fun `request expires when no new snapshot arrives`() {
        val coordinatorScheduler = ManualObservationScheduler()
        val publisher = publisher(ManualObservationScheduler())
        val terminal = mutableListOf<TerminalAck>()
        AccessibilityObservationBus.publish(
            AccessibilityObserverState(
                serviceConnected = true,
                latestSnapshot = snapshot(BASELINE_SNAPSHOT_ID, 1_000, "com.example"),
            ),
        )
        val coordinator = coordinator(
            publisher = publisher,
            scheduler = coordinatorScheduler,
            captureRequester = { true },
            terminal = terminal,
        )

        try {
            val receipt = coordinator.receive(
                REQUEST_ID,
                request(REQUEST_ID, timeoutMs = 250),
            )
            assertEquals(ObservationRefreshAckStatus.ACCEPTED, receipt.status)

            coordinatorScheduler.advanceBy(250)

            assertEquals(
                listOf(
                    TerminalAck(
                        requestId = REQUEST_ID,
                        status = ObservationRefreshAckStatus.EXPIRED,
                        detail = "no new Accessibility snapshot arrived before refresh timeout",
                    ),
                ),
                terminal,
            )
            assertNull(publisher.pendingRefreshRequestId())
        } finally {
            coordinator.close()
            publisher.close()
        }
    }

    @Test
    fun `observer unavailable is reported before capture ownership`() {
        val publisher = publisher(ManualObservationScheduler())
        val captures = AtomicInteger(0)
        val coordinator = coordinator(
            publisher = publisher,
            scheduler = ManualObservationScheduler(),
            captureRequester = { captures.incrementAndGet(); true },
            terminal = mutableListOf(),
        )

        try {
            val receipt = coordinator.receive(REQUEST_ID, request(REQUEST_ID))

            assertEquals(ObservationRefreshAckStatus.OBSERVER_UNAVAILABLE, receipt.status)
            assertEquals(0, captures.get())
        } finally {
            coordinator.close()
            publisher.close()
        }
    }

    @Test
    fun `observer disconnect terminalizes active request`() {
        val publisher = publisher(ManualObservationScheduler())
        val terminal = mutableListOf<TerminalAck>()
        AccessibilityObservationBus.publish(
            AccessibilityObserverState(
                serviceConnected = true,
                latestSnapshot = snapshot(BASELINE_SNAPSHOT_ID, 1_000, "com.example"),
            ),
        )
        val coordinator = coordinator(
            publisher = publisher,
            scheduler = ManualObservationScheduler(),
            captureRequester = { true },
            terminal = terminal,
        )

        try {
            assertEquals(
                ObservationRefreshAckStatus.ACCEPTED,
                coordinator.receive(REQUEST_ID, request(REQUEST_ID)).status,
            )

            AccessibilityObservationBus.publish(
                AccessibilityObserverState(serviceConnected = false),
            )

            assertEquals(1, terminal.size)
            assertEquals(REQUEST_ID, terminal.single().requestId)
            assertEquals(
                ObservationRefreshAckStatus.OBSERVER_UNAVAILABLE,
                terminal.single().status,
            )
        } finally {
            coordinator.close()
            publisher.close()
        }
    }

    @Test
    fun `capture requester disappearance returns immediate observer unavailable`() {
        val publisher = publisher(ManualObservationScheduler())
        AccessibilityObservationBus.publish(
            AccessibilityObserverState(
                serviceConnected = true,
                latestSnapshot = snapshot(BASELINE_SNAPSHOT_ID, 1_000, "com.example"),
            ),
        )
        val coordinator = coordinator(
            publisher = publisher,
            scheduler = ManualObservationScheduler(),
            captureRequester = { false },
            terminal = mutableListOf(),
        )

        try {
            val receipt = coordinator.receive(REQUEST_ID, request(REQUEST_ID))

            assertEquals(ObservationRefreshAckStatus.OBSERVER_UNAVAILABLE, receipt.status)
            assertNull(publisher.pendingRefreshRequestId())
        } finally {
            coordinator.close()
            publisher.close()
        }
    }

    private fun connectedCoordinator(
        publisher: AccessibilityObservationPublisher,
    ): AccessibilityRefreshCoordinator {
        AccessibilityObservationBus.publish(
            AccessibilityObserverState(
                serviceConnected = true,
                latestSnapshot = snapshot(BASELINE_SNAPSHOT_ID, 1_000, "com.example"),
            ),
        )
        return coordinator(
            publisher = publisher,
            scheduler = ManualObservationScheduler(),
            captureRequester = { true },
            terminal = mutableListOf(),
        )
    }

    private fun coordinator(
        publisher: AccessibilityObservationPublisher,
        scheduler: ManualObservationScheduler,
        captureRequester: () -> Boolean,
        terminal: MutableList<TerminalAck>,
    ): AccessibilityRefreshCoordinator = AccessibilityRefreshCoordinator(
        publisher = publisher,
        captureRequester = captureRequester,
        terminalAcknowledgementEmitter = { requestId, status, detail ->
            terminal += TerminalAck(requestId, status, detail)
        },
        scheduler = scheduler,
    )

    private fun publisher(
        scheduler: ManualObservationScheduler,
    ): AccessibilityObservationPublisher = AccessibilityObservationPublisher(
        deviceId = DEVICE_ID,
        sender = { true },
        scheduler = scheduler,
        minimumSendIntervalMillis = 0,
        acknowledgementTimeoutMillis = 1_000,
        streamId = STREAM_ID,
    )

    private fun request(
        requestId: String,
        timeoutMs: Long = 5_000,
    ): DeviceObservationRefreshPayload = DeviceObservationRefreshPayload(
        requestId = requestId,
        timeoutMs = timeoutMs,
        expectedStateFingerprint = null,
        expectedActivePackage = null,
        reason = "fixture refresh",
    )

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
        const val REQUEST_ID = "33333333-3333-3333-3333-333333333333"
        const val OTHER_REQUEST_ID = "44444444-4444-4444-4444-444444444444"
        const val BASELINE_SNAPSHOT_ID = "55555555-5555-5555-5555-555555555555"
        const val NEW_SNAPSHOT_ID = "66666666-6666-6666-6666-666666666666"
    }
}
