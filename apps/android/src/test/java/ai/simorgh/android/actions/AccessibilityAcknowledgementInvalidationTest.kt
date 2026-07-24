package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilityAcknowledgementBus
import ai.simorgh.android.accessibility.AccessibilityObservationBus
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.accessibility.AcknowledgedAccessibilityObservation
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

class AccessibilityAcknowledgementInvalidationTest {
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
    fun `connection invalidation clears old evidence but preserves the live subscriber`() {
        val first = acknowledged(
            sequence = 1,
            snapshotId = FIRST_SNAPSHOT_ID,
            activePackage = "com.example.first",
        )
        AccessibilityAcknowledgementBus.publish(first)
        val source = AccessibilityActionEvidenceSource(
            captureRequester = { false },
            pollIntervalMillis = 25,
        )
        try {
            assertEquals(FIRST_SNAPSHOT_ID, source.latestAcknowledged()?.snapshotId)

            AccessibilityAcknowledgementBus.reset()
            assertNull(source.latestAcknowledged())

            val second = acknowledged(
                sequence = 2,
                snapshotId = SECOND_SNAPSHOT_ID,
                activePackage = "com.example.second",
            )
            AccessibilityAcknowledgementBus.publish(second)

            assertEquals(SECOND_SNAPSHOT_ID, source.latestAcknowledged()?.snapshotId)
            assertEquals("com.example.second", source.latestAcknowledged()?.activePackage)
        } finally {
            source.close()
        }
    }

    private fun acknowledged(
        sequence: Long,
        snapshotId: String,
        activePackage: String,
    ): AcknowledgedAccessibilityObservation {
        val snapshot = AccessibilitySnapshot(
            snapshotId = snapshotId,
            capturedAtMs = 1_000 + sequence,
            activePackage = activePackage,
            windows = emptyList(),
            nodes = emptyList(),
            truncated = false,
            truncationReasons = emptyList(),
            maxDepthObserved = 0,
        )
        return AcknowledgedAccessibilityObservation(
            streamId = STREAM_ID,
            sequence = sequence,
            stateFingerprint = AccessibilitySnapshotFingerprint.calculate(snapshot),
            snapshot = snapshot,
            acknowledgedAtMs = snapshot.capturedAtMs + 1,
        )
    }

    private companion object {
        const val STREAM_ID = "11111111-1111-1111-1111-111111111111"
        const val FIRST_SNAPSHOT_ID = "22222222-2222-2222-2222-222222222222"
        const val SECOND_SNAPSHOT_ID = "33333333-3333-3333-3333-333333333333"
    }
}
