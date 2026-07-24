package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilityNodeSnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.ScreenBounds
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NodeSelectorMatcherTest {
    @Test
    fun `Persian normalizer aligns Arabic letters digits and half spaces`() {
        val first = PersianTextNormalizer.normalize("  مي\u200Cخواهم ۱۲۳  ")
        val second = PersianTextNormalizer.normalize("می خواهم 123")

        assertEquals(second, first)
    }

    @Test
    fun `view id and capability resolve one deterministic button`() {
        val target = node(
            id = "1".repeat(24),
            path = "0.0",
            viewId = "com.example:id/continue_button",
            text = "ادامه",
            clickable = true,
        )
        val other = node(
            id = "2".repeat(24),
            path = "0.1",
            viewId = "com.example:id/cancel_button",
            text = "لغو",
            clickable = true,
        )
        val selector = AndroidNodeSelector(
            packageName = PACKAGE_NAME,
            viewId = target.viewId,
            text = TextCriterion("ادامه"),
            className = target.className,
            requiredFields = setOf(SelectorField.VIEW_ID),
            requiredCapabilities = setOf(NodeCapability.CLICKABLE),
        )

        val resolution = NodeSelectorMatcher.resolve(snapshot(target, other), selector)

        assertEquals(SelectorResolutionOutcome.RESOLVED, resolution.outcome)
        assertEquals(target.nodeId, resolution.selected?.node?.nodeId)
        assertTrue(resolution.selected!!.score >= selector.minimumScore)
    }

    @Test
    fun `same text candidates are blocked as ambiguous`() {
        val first = node(
            id = "1".repeat(24),
            path = "0.0",
            text = "ارسال",
            clickable = true,
        )
        val second = node(
            id = "2".repeat(24),
            path = "0.1",
            text = "ارسال",
            clickable = true,
        )
        val selector = AndroidNodeSelector(
            packageName = PACKAGE_NAME,
            text = TextCriterion("ارسال"),
            className = first.className,
            requiredFields = setOf(SelectorField.TEXT),
            requiredCapabilities = setOf(NodeCapability.CLICKABLE),
            minimumMargin = 20,
        )

        val resolution = NodeSelectorMatcher.resolve(snapshot(first, second), selector)

        assertEquals(SelectorResolutionOutcome.AMBIGUOUS, resolution.outcome)
        assertNull(resolution.selected)
        assertEquals(0, resolution.scoreMargin)
        assertEquals(2, resolution.candidates.size)
    }

    @Test
    fun `required field mismatch rejects a superficially similar node`() {
        val node = node(
            id = "1".repeat(24),
            path = "0.0",
            viewId = "com.example:id/destructive",
            text = "ادامه",
            clickable = true,
        )
        val selector = AndroidNodeSelector(
            packageName = PACKAGE_NAME,
            viewId = "com.example:id/safe_continue",
            text = TextCriterion("ادامه"),
            requiredFields = setOf(SelectorField.VIEW_ID),
            requiredCapabilities = setOf(NodeCapability.CLICKABLE),
        )

        val resolution = NodeSelectorMatcher.resolve(snapshot(node), selector)

        assertEquals(SelectorResolutionOutcome.NOT_FOUND, resolution.outcome)
    }

    @Test
    fun `hidden and disabled nodes never become action targets`() {
        val hidden = node(
            id = "1".repeat(24),
            path = "0.0",
            viewId = "com.example:id/continue",
            clickable = true,
            visible = false,
        )
        val disabled = node(
            id = "2".repeat(24),
            path = "0.1",
            viewId = "com.example:id/continue",
            clickable = true,
            enabled = false,
        )
        val selector = AndroidNodeSelector(
            packageName = PACKAGE_NAME,
            viewId = "com.example:id/continue",
            requiredFields = setOf(SelectorField.VIEW_ID),
            requiredCapabilities = setOf(NodeCapability.CLICKABLE),
        )

        val resolution = NodeSelectorMatcher.resolve(snapshot(hidden, disabled), selector)

        assertEquals(SelectorResolutionOutcome.NOT_FOUND, resolution.outcome)
    }

    @Test
    fun `bounds and path create an explainable margin`() {
        val expectedBounds = ScreenBounds(0, 100, 400, 200)
        val target = node(
            id = "1".repeat(24),
            path = "0.2",
            text = "تنظیمات",
            bounds = expectedBounds,
        )
        val other = node(
            id = "2".repeat(24),
            path = "0.3",
            text = "تنظیمات",
            bounds = ScreenBounds(0, 400, 400, 500),
        )
        val selector = AndroidNodeSelector(
            packageName = PACKAGE_NAME,
            text = TextCriterion("تنظیمات"),
            path = target.path,
            bounds = expectedBounds,
            requiredFields = setOf(SelectorField.TEXT),
            minimumMargin = 20,
        )

        val resolution = NodeSelectorMatcher.resolve(snapshot(target, other), selector)

        assertEquals(SelectorResolutionOutcome.RESOLVED, resolution.outcome)
        assertEquals(target.nodeId, resolution.selected?.node?.nodeId)
        assertTrue((resolution.scoreMargin ?: 0) >= 20)
        assertTrue("path" in resolution.selected!!.matchedSignals)
        assertTrue(resolution.selected!!.matchedSignals.any { it.startsWith("bounds_iou_") })
    }

    private fun snapshot(vararg nodes: AccessibilityNodeSnapshot): AccessibilitySnapshot =
        AccessibilitySnapshot(
            snapshotId = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            capturedAtMs = 1_000,
            activePackage = PACKAGE_NAME,
            activeWindowId = 1,
            rootNodeId = nodes.firstOrNull()?.nodeId,
            windows = emptyList(),
            nodes = nodes.toList(),
            truncated = false,
            truncationReasons = emptyList(),
            maxDepthObserved = nodes.maxOfOrNull(AccessibilityNodeSnapshot::depth) ?: 0,
        )

    private fun node(
        id: String,
        path: String,
        viewId: String? = null,
        text: String? = null,
        bounds: ScreenBounds = ScreenBounds(0, 0, 100, 100),
        clickable: Boolean = false,
        visible: Boolean = true,
        enabled: Boolean = true,
        checked: Boolean = false,
    ): AccessibilityNodeSnapshot = AccessibilityNodeSnapshot(
        nodeId = id,
        path = path,
        depth = path.count { it == '.' },
        windowId = 1,
        packageName = PACKAGE_NAME,
        className = "android.widget.Button",
        viewId = viewId,
        text = text,
        bounds = bounds,
        semanticFingerprint = id,
        childCount = 0,
        inputType = 0,
        clickable = clickable,
        longClickable = false,
        focusable = true,
        focused = false,
        editable = false,
        scrollable = false,
        enabled = enabled,
        selected = false,
        checkable = checked,
        checked = checked,
        visibleToUser = visible,
        accessibilityFocused = false,
        password = false,
        heading = false,
        actions = emptyList(),
    )

    private companion object {
        const val PACKAGE_NAME = "com.example"
    }
}
