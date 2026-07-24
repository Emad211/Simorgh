package ai.simorgh.android.accessibility

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class AccessibilitySnapshotProjectionTest {
    @Test
    fun `external application snapshots remain unchanged`() {
        val external = snapshot(
            id = EXTERNAL_SNAPSHOT_ID,
            activePackage = EXTERNAL_PACKAGE,
            activeWindowId = 7,
            text = "محتوای خارجی",
        )

        val projected = AccessibilitySnapshotProjection.forDeviceTransport(
            snapshot = external,
            simorghPackageName = SIMORGH_PACKAGE,
        )

        assertSame(external, projected)
    }

    @Test
    fun `Simorgh self snapshot retains only package-level state`() {
        val self = snapshot(
            id = SELF_SNAPSHOT_ID,
            activePackage = SIMORGH_PACKAGE,
            activeWindowId = 9,
            text = "توکن و وضعیت داخلی",
        )

        val projected = AccessibilitySnapshotProjection.forDeviceTransport(
            snapshot = self,
            simorghPackageName = SIMORGH_PACKAGE,
        )

        assertEquals(SELF_SNAPSHOT_ID, projected.snapshotId)
        assertEquals(SIMORGH_PACKAGE, projected.activePackage)
        assertNull(projected.activeWindowId)
        assertNull(projected.rootNodeId)
        assertTrue(projected.windows.isEmpty())
        assertTrue(projected.nodes.isEmpty())
        assertTrue(projected.truncationReasons.isEmpty())
        assertEquals(0, projected.maxDepthObserved)
    }

    @Test
    fun `different Simorgh screens produce the same projected state fingerprint`() {
        val first = snapshot(
            id = SELF_SNAPSHOT_ID,
            activePackage = SIMORGH_PACKAGE,
            activeWindowId = 1,
            text = "صفحه اتصال",
        )
        val second = snapshot(
            id = SECOND_SELF_SNAPSHOT_ID,
            activePackage = SIMORGH_PACKAGE,
            activeWindowId = 99,
            text = "صفحه وضعیت جدید",
        )

        val firstProjected = AccessibilitySnapshotProjection.forDeviceTransport(
            snapshot = first,
            simorghPackageName = SIMORGH_PACKAGE,
        )
        val secondProjected = AccessibilitySnapshotProjection.forDeviceTransport(
            snapshot = second,
            simorghPackageName = SIMORGH_PACKAGE,
        )

        assertEquals(
            AccessibilitySnapshotFingerprint.calculate(firstProjected),
            AccessibilitySnapshotFingerprint.calculate(secondProjected),
        )
    }

    private fun snapshot(
        id: String,
        activePackage: String,
        activeWindowId: Int,
        text: String,
    ): AccessibilitySnapshot {
        val root = AccessibilityNodeSnapshot(
            nodeId = "a".repeat(24),
            path = "0",
            depth = 0,
            windowId = activeWindowId,
            packageName = activePackage,
            className = "android.widget.TextView",
            text = text,
            bounds = ScreenBounds(0, 0, 100, 100),
            semanticFingerprint = "b".repeat(24),
            childCount = 0,
            inputType = 0,
            clickable = false,
            longClickable = false,
            focusable = false,
            focused = false,
            editable = false,
            scrollable = false,
            enabled = true,
            selected = false,
            checkable = false,
            checked = false,
            visibleToUser = true,
            accessibilityFocused = false,
            password = false,
            heading = false,
            actions = emptyList(),
        )
        return AccessibilitySnapshot(
            snapshotId = id,
            capturedAtMs = 1_000,
            triggeringEventType = 32,
            activePackage = activePackage,
            activeWindowId = activeWindowId,
            rootNodeId = root.nodeId,
            windows = emptyList(),
            nodes = listOf(root),
            truncated = false,
            truncationReasons = emptyList(),
            maxDepthObserved = 0,
        )
    }

    private companion object {
        const val SIMORGH_PACKAGE = "ai.simorgh.android"
        const val EXTERNAL_PACKAGE = "com.example.external"
        const val EXTERNAL_SNAPSHOT_ID = "11111111-1111-1111-1111-111111111111"
        const val SELF_SNAPSHOT_ID = "22222222-2222-2222-2222-222222222222"
        const val SECOND_SELF_SNAPSHOT_ID = "33333333-3333-3333-3333-333333333333"
    }
}
