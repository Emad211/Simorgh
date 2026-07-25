package ai.simorgh.android.accessibility

import ai.simorgh.android.protocol.DeviceProtocol
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class MonotonicSnapshotWireTest {
    @Test
    fun `local monotonic capture time adds no wire field`() {
        val snapshot = snapshot(capturedAtElapsedRealtimeMs = 123)

        val encoded = DeviceProtocol.json.encodeToString(snapshot)
        val decoded = DeviceProtocol.json.decodeFromString<AccessibilitySnapshot>(encoded)

        assertFalse(encoded.contains("captured_at_elapsed"))
        assertFalse(encoded.contains("capturedAtElapsed"))
        assertEquals(snapshot.capturedAtMs, decoded.capturedAtMs)
        assertEquals(
            decoded.capturedAtMs,
            decoded.capturedAtElapsedRealtimeMs,
        )
    }

    @Test
    fun `monotonic capture time cannot change canonical UI fingerprint`() {
        val first = snapshot(capturedAtElapsedRealtimeMs = 123)
        val second = first.copy(capturedAtElapsedRealtimeMs = 999_999)

        assertEquals(
            AccessibilitySnapshotFingerprint.calculate(first),
            AccessibilitySnapshotFingerprint.calculate(second),
        )
    }

    private fun snapshot(capturedAtElapsedRealtimeMs: Long): AccessibilitySnapshot =
        AccessibilitySnapshot(
            snapshotId = "11111111-1111-1111-1111-111111111111",
            capturedAtMs = 50_000,
            capturedAtElapsedRealtimeMs = capturedAtElapsedRealtimeMs,
            activePackage = "com.example",
            activeWindowId = 1,
            windows = emptyList(),
            nodes = emptyList(),
            truncated = false,
            truncationReasons = emptyList(),
            maxDepthObserved = 0,
        )
}
