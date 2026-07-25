package ai.simorgh.android.accessibility

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AccessibilityTreeSnapshotBuilderTest {
    @Test
    fun `builder flattens a Persian tree and closes all readers`() {
        val child = FakeNode(
            className = "android.widget.Button",
            text = "  ادامه   بده  ",
            viewId = "com.example:id/continue_button",
            bounds = ScreenBounds(10, 100, 300, 180),
            clickable = true,
        )
        val root = FakeNode(
            packageName = "com.example",
            className = "android.widget.FrameLayout",
            text = "سلام   دنیا",
            bounds = ScreenBounds(0, 0, 1080, 2400),
            children = listOf(child),
        )

        val snapshot = builder().build(
            root = root,
            windows = emptyList(),
            triggeringEventType = 32,
            activePackageHint = null,
            activeWindowIdHint = null,
            capturedAtMs = 123_456,
            snapshotId = "snapshot-1",
        )

        assertEquals("snapshot-1", snapshot.snapshotId)
        assertEquals(654_321, snapshot.capturedAtElapsedRealtimeMs)
        assertEquals("com.example", snapshot.activePackage)
        assertEquals(2, snapshot.nodes.size)
        assertEquals("سلام دنیا", snapshot.nodes[0].text)
        assertEquals("ادامه بده", snapshot.nodes[1].text)
        assertEquals("0.0", snapshot.nodes[1].path)
        assertEquals(snapshot.nodes[0].nodeId, snapshot.nodes[1].parentNodeId)
        assertFalse(snapshot.truncated)
        assertTrue(root.closed)
        assertTrue(child.closed)
    }

    @Test
    fun `live root identity overrides stale event hints`() {
        val root = FakeNode(
            windowId = 9,
            packageName = "com.current.app",
            className = "android.widget.FrameLayout",
        )

        val snapshot = builder().build(
            root = root,
            windows = emptyList(),
            triggeringEventType = 32,
            activePackageHint = "com.previous.app",
            activeWindowIdHint = 7,
            capturedAtMs = 123_456,
            snapshotId = "root-wins",
        )

        assertEquals("com.current.app", snapshot.activePackage)
        assertEquals(9, snapshot.activeWindowId)
        assertTrue(root.closed)
    }

    @Test
    fun `password nodes never retain semantic text`() {
        val root = FakeNode(
            className = "android.widget.EditText",
            text = "123456",
            contentDescription = "رمز حساب",
            hintText = "رمز را وارد کنید",
            stateDescription = "شش رقم وارد شده",
            password = true,
            editable = true,
        )

        val node = builder().build(
            root = root,
            windows = emptyList(),
            triggeringEventType = null,
            activePackageHint = "com.bank",
            activeWindowIdHint = 7,
            snapshotId = "password-snapshot",
        ).nodes.single()

        assertTrue(node.password)
        assertNull(node.text)
        assertNull(node.contentDescription)
        assertNull(node.hintText)
        assertNull(node.stateDescription)
        assertTrue(root.closed)
    }

    @Test
    fun `node limit closes queued readers and reports truncation`() {
        val children = List(3) { index ->
            FakeNode(text = "child-$index")
        }
        val root = FakeNode(children = children)
        val builder = builder(
            AccessibilitySnapshotLimits(maxNodes = 2),
        )

        val snapshot = builder.build(
            root = root,
            windows = emptyList(),
            triggeringEventType = null,
            activePackageHint = null,
            activeWindowIdHint = null,
            snapshotId = "limited",
        )

        assertEquals(2, snapshot.nodes.size)
        assertTrue(snapshot.truncated)
        assertTrue("node_limit" in snapshot.truncationReasons)
        assertTrue(root.closed)
        assertTrue(children.all(FakeNode::closed))
    }

    @Test
    fun `depth limit prevents unbounded descent`() {
        val child = FakeNode(text = "child")
        val root = FakeNode(children = listOf(child))
        val builder = builder(
            AccessibilitySnapshotLimits(maxDepth = 0),
        )

        val snapshot = builder.build(
            root = root,
            windows = emptyList(),
            triggeringEventType = null,
            activePackageHint = null,
            activeWindowIdHint = null,
            snapshotId = "depth-limited",
        )

        assertEquals(1, snapshot.nodes.size)
        assertTrue(snapshot.truncated)
        assertTrue("depth_limit" in snapshot.truncationReasons)
        assertTrue(root.closed)
        assertFalse(child.closed)
    }

    private fun builder(
        limits: AccessibilitySnapshotLimits = AccessibilitySnapshotLimits(),
    ): AccessibilityTreeSnapshotBuilder = AccessibilityTreeSnapshotBuilder(
        limits = limits,
        wallClockMillis = { 123_456 },
        monotonicMillis = { 654_321 },
    )

    private class FakeNode(
        override val windowId: Int = 1,
        override val packageName: String? = null,
        override val className: String? = null,
        override val viewId: String? = null,
        override val text: String? = null,
        override val contentDescription: String? = null,
        override val hintText: String? = null,
        override val stateDescription: String? = null,
        override val bounds: ScreenBounds = ScreenBounds(0, 0, 10, 10),
        override val inputType: Int = 0,
        override val clickable: Boolean = false,
        override val longClickable: Boolean = false,
        override val focusable: Boolean = false,
        override val focused: Boolean = false,
        override val editable: Boolean = false,
        override val scrollable: Boolean = false,
        override val enabled: Boolean = true,
        override val selected: Boolean = false,
        override val checkable: Boolean = false,
        override val checked: Boolean = false,
        override val visibleToUser: Boolean = true,
        override val accessibilityFocused: Boolean = false,
        override val password: Boolean = false,
        override val heading: Boolean = false,
        override val actions: List<RawAccessibilityAction> = emptyList(),
        private val children: List<FakeNode> = emptyList(),
    ) : AccessibilityNodeReader {
        var closed: Boolean = false
            private set

        override val childCount: Int
            get() = children.size

        override fun childAt(index: Int): AccessibilityNodeReader? = children.getOrNull(index)

        override fun close() {
            closed = true
        }
    }
}
