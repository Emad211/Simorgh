package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilityAcknowledgementBus
import ai.simorgh.android.accessibility.AccessibilityObservationBus
import ai.simorgh.android.accessibility.AccessibilityObserverState
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.accessibility.AcknowledgedAccessibilityObservation
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.Executors
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

class AccessibilityActionEvidenceSourceTest {
    @Before
    fun resetBuses() {
        AccessibilityObservationBus.clearForTest()
        AccessibilityAcknowledgementBus.clearForTest()
    }

    @After
    fun cleanupBuses() {
        AccessibilityObservationBus.clearForTest()
        AccessibilityAcknowledgementBus.clearForTest()
    }

    @Test
    fun `explicit capture returns a newer local snapshot`() {
        val captureRequests = LinkedBlockingQueue<Unit>()
        val baseline = snapshot(
            id = BASELINE_SNAPSHOT_ID,
            capturedAtMs = 900,
            activePackage = SOURCE_PACKAGE,
        )
        AccessibilityObservationBus.publish(
            AccessibilityObserverState(
                serviceConnected = true,
                latestSnapshot = baseline,
            ),
        )
        val source = AccessibilityActionEvidenceSource(
            captureRequester = {
                captureRequests.offer(Unit)
                true
            },
            wallClockMillis = { 1_000 },
            pollIntervalMillis = 25,
        )
        val executor = Executors.newSingleThreadExecutor()
        try {
            val future = executor.submit<AccessibilitySnapshot?> {
                source.requestFreshLocalSnapshot(timeoutMillis = 1_000) { false }
            }
            assertNotNull(captureRequests.poll(1, TimeUnit.SECONDS))

            val fresh = baseline.copy(
                snapshotId = FRESH_SNAPSHOT_ID,
                capturedAtMs = 1_000,
            )
            AccessibilityObservationBus.publish(
                AccessibilityObserverState(
                    serviceConnected = true,
                    latestSnapshot = fresh,
                ),
            )

            assertEquals(FRESH_SNAPSHOT_ID, future.get(1, TimeUnit.SECONDS)?.snapshotId)
        } finally {
            source.close()
            executor.shutdownNow()
        }
    }

    @Test
    fun `stable local samples require a matching newer Core acknowledgement`() {
        val captureRequests = LinkedBlockingQueue<Unit>()
        val beforeSnapshot = snapshot(
            id = BASELINE_SNAPSHOT_ID,
            capturedAtMs = 1_900,
            activePackage = SOURCE_PACKAGE,
        )
        val before = acknowledged(sequence = 4, snapshot = beforeSnapshot)
        publishLocal(beforeSnapshot)
        AccessibilityAcknowledgementBus.publish(before)

        val source = AccessibilityActionEvidenceSource(
            captureRequester = {
                captureRequests.offer(Unit)
                true
            },
            pollIntervalMillis = 25,
        )
        val executor = Executors.newSingleThreadExecutor()
        val policy = AndroidVerificationPolicy(
            predicates = listOf(ActivePackageEqualsPredicate(TARGET_PACKAGE)),
            timeoutMs = 1_000,
            stableSamples = 2,
        )
        try {
            val future = executor.submit<PostActionEvidenceResult> {
                source.awaitVerifiedObservation(
                    before = before,
                    launchedAtElapsedRealtimeMs = 2_000,
                    policy = policy,
                    timeoutMillis = 1_000,
                    cancelled = { false },
                )
            }

            assertNotNull(captureRequests.poll(1, TimeUnit.SECONDS))
            val first = snapshot(
                id = FIRST_POST_SNAPSHOT_ID,
                capturedAtMs = 2_010,
                activePackage = TARGET_PACKAGE,
            )
            publishLocal(first)

            assertNotNull(captureRequests.poll(1, TimeUnit.SECONDS))
            val second = first.copy(
                snapshotId = SECOND_POST_SNAPSHOT_ID,
                capturedAtMs = 2_020,
            )
            publishLocal(second)
            AccessibilityAcknowledgementBus.publish(
                acknowledged(sequence = 5, snapshot = first),
            )

            val result = future.get(1, TimeUnit.SECONDS)
            assertEquals(PostActionEvidenceStatus.SATISFIED, result.status)
            assertEquals(FIRST_POST_SNAPSHOT_ID, result.observation?.snapshotId)
            assertEquals(PredicateOutcome.SATISFIED, result.evaluation?.outcome)
            assertTrue(result.detail.contains("Core ACK"))
        } finally {
            source.close()
            executor.shutdownNow()
        }
    }

    @Test
    fun `newer unsatisfied snapshot prevents success from an older matching acknowledgement`() {
        val beforeSnapshot = snapshot(
            id = BASELINE_SNAPSHOT_ID,
            capturedAtMs = 1_900,
            activePackage = SOURCE_PACKAGE,
        )
        val before = acknowledged(sequence = 4, snapshot = beforeSnapshot)
        publishLocal(beforeSnapshot)
        AccessibilityAcknowledgementBus.publish(before)

        val source = AccessibilityActionEvidenceSource(
            captureRequester = { true },
            pollIntervalMillis = 25,
        )
        val executor = Executors.newSingleThreadExecutor()
        val policy = AndroidVerificationPolicy(
            predicates = listOf(ActivePackageEqualsPredicate(TARGET_PACKAGE)),
            timeoutMs = 250,
            stableSamples = 2,
        )
        try {
            val future = executor.submit<PostActionEvidenceResult> {
                source.awaitVerifiedObservation(
                    before = before,
                    launchedAtElapsedRealtimeMs = 2_000,
                    policy = policy,
                    timeoutMillis = 250,
                    cancelled = { false },
                )
            }

            val first = snapshot(
                id = FIRST_POST_SNAPSHOT_ID,
                capturedAtMs = 2_010,
                activePackage = TARGET_PACKAGE,
            )
            val second = first.copy(
                snapshotId = SECOND_POST_SNAPSHOT_ID,
                capturedAtMs = 2_020,
            )
            val regressed = snapshot(
                id = REGRESSED_SNAPSHOT_ID,
                capturedAtMs = 2_030,
                activePackage = SOURCE_PACKAGE,
            )
            publishLocal(first)
            publishLocal(second)
            publishLocal(regressed)
            AccessibilityAcknowledgementBus.publish(
                acknowledged(sequence = 5, snapshot = first),
            )

            val result = future.get(1, TimeUnit.SECONDS)
            assertNotEquals(PostActionEvidenceStatus.SATISFIED, result.status)
            assertEquals(PredicateOutcome.UNSATISFIED, result.evaluation?.outcome)
        } finally {
            source.close()
            executor.shutdownNow()
        }
    }

    private fun publishLocal(snapshot: AccessibilitySnapshot) {
        AccessibilityObservationBus.publish(
            AccessibilityObserverState(
                serviceConnected = true,
                latestSnapshot = snapshot,
            ),
        )
    }

    private fun acknowledged(
        sequence: Long,
        snapshot: AccessibilitySnapshot,
    ): AcknowledgedAccessibilityObservation = AcknowledgedAccessibilityObservation(
        streamId = STREAM_ID,
        sequence = sequence,
        stateFingerprint = AccessibilitySnapshotFingerprint.calculate(snapshot),
        snapshot = snapshot,
        acknowledgedAtMs = snapshot.capturedAtMs + 1,
    )

    private fun snapshot(
        id: String,
        capturedAtMs: Long,
        activePackage: String,
    ): AccessibilitySnapshot = AccessibilitySnapshot(
        snapshotId = id,
        capturedAtMs = capturedAtMs,
        activePackage = activePackage,
        activeWindowId = 1,
        windows = emptyList(),
        nodes = emptyList(),
        truncated = false,
        truncationReasons = emptyList(),
        maxDepthObserved = 0,
    )

    private companion object {
        const val STREAM_ID = "11111111-1111-1111-1111-111111111111"
        const val BASELINE_SNAPSHOT_ID = "22222222-2222-2222-2222-222222222222"
        const val FRESH_SNAPSHOT_ID = "33333333-3333-3333-3333-333333333333"
        const val FIRST_POST_SNAPSHOT_ID = "44444444-4444-4444-4444-444444444444"
        const val SECOND_POST_SNAPSHOT_ID = "55555555-5555-5555-5555-555555555555"
        const val REGRESSED_SNAPSHOT_ID = "66666666-6666-6666-6666-666666666666"
        const val SOURCE_PACKAGE = "com.android.launcher"
        const val TARGET_PACKAGE = "com.example.target"
    }
}
