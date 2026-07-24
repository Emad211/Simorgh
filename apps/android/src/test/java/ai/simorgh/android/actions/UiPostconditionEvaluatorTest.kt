package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilityNodeSnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.ScreenBounds
import org.junit.Assert.assertEquals
import org.junit.Test

class UiPostconditionEvaluatorTest {
    @Test
    fun `all package and checked predicates can be satisfied`() {
        val checkbox = node(checked = true)
        val selector = selector()
        val policy = AndroidVerificationPolicy(
            predicates = listOf(
                ActivePackageEqualsPredicate(PACKAGE_NAME),
                NodeExistsPredicate(selector),
                NodeCheckedEqualsPredicate(selector, expectedChecked = true),
            ),
        )

        val evaluation = UiPostconditionEvaluator.evaluate(snapshot(checkbox), policy)

        assertEquals(PredicateOutcome.SATISFIED, evaluation.outcome)
        assertEquals(3, evaluation.evidence.size)
        assertEquals(
            listOf(
                PredicateOutcome.SATISFIED,
                PredicateOutcome.SATISFIED,
                PredicateOutcome.SATISFIED,
            ),
            evaluation.evidence.map(PredicateEvidence::outcome),
        )
    }

    @Test
    fun `wrong checked state is unsatisfied rather than indeterminate`() {
        val policy = AndroidVerificationPolicy(
            predicates = listOf(
                NodeCheckedEqualsPredicate(selector(), expectedChecked = true),
            ),
        )

        val evaluation = UiPostconditionEvaluator.evaluate(snapshot(node(checked = false)), policy)

        assertEquals(PredicateOutcome.UNSATISFIED, evaluation.outcome)
        assertEquals(PredicateOutcome.UNSATISFIED, evaluation.evidence.single().outcome)
    }

    @Test
    fun `verification can resolve a visible disabled node`() {
        val policy = AndroidVerificationPolicy(
            predicates = listOf(
                NodeEnabledEqualsPredicate(selector(), expectedEnabled = false),
            ),
        )

        val evaluation = UiPostconditionEvaluator.evaluate(
            snapshot(node(enabled = false)),
            policy,
        )

        assertEquals(PredicateOutcome.SATISFIED, evaluation.outcome)
        assertEquals(PredicateOutcome.SATISFIED, evaluation.evidence.single().outcome)
    }

    @Test
    fun `ambiguous selector makes verification indeterminate`() {
        val selector = AndroidNodeSelector(
            packageName = PACKAGE_NAME,
            text = TextCriterion("ذخیره"),
            requiredFields = setOf(SelectorField.TEXT),
            requiredCapabilities = setOf(NodeCapability.CLICKABLE),
        )
        val policy = AndroidVerificationPolicy(
            predicates = listOf(NodeExistsPredicate(selector)),
        )
        val first = node(id = "1".repeat(24), path = "0.0", text = "ذخیره")
        val second = node(id = "2".repeat(24), path = "0.1", text = "ذخیره")

        val evaluation = UiPostconditionEvaluator.evaluate(snapshot(first, second), policy)

        assertEquals(PredicateOutcome.INDETERMINATE, evaluation.outcome)
        assertEquals(
            SelectorResolutionOutcome.AMBIGUOUS.name.lowercase(),
            evaluation.evidence.single().resolution?.outcome,
        )
    }

    @Test
    fun `node absence is satisfied only when no target is resolved`() {
        val policy = AndroidVerificationPolicy(
            predicates = listOf(NodeAbsentPredicate(selector())),
        )

        val present = UiPostconditionEvaluator.evaluate(snapshot(node()), policy)
        val absent = UiPostconditionEvaluator.evaluate(snapshot(), policy)

        assertEquals(PredicateOutcome.UNSATISFIED, present.outcome)
        assertEquals(PredicateOutcome.SATISFIED, absent.outcome)
    }

    @Test
    fun `text equality uses the same Persian normalization as selection`() {
        val selector = selector()
        val policy = AndroidVerificationPolicy(
            predicates = listOf(
                NodeTextEqualsPredicate(
                    selector = selector,
                    expectedText = "مي خواهم 123",
                ),
            ),
        )

        val evaluation = UiPostconditionEvaluator.evaluate(
            snapshot(node(text = "می\u200Cخواهم ۱۲۳")),
            policy,
        )

        assertEquals(PredicateOutcome.SATISFIED, evaluation.outcome)
    }

    private fun selector(): AndroidNodeSelector = AndroidNodeSelector(
        packageName = PACKAGE_NAME,
        viewId = VIEW_ID,
        requiredFields = setOf(SelectorField.VIEW_ID),
    )

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
        id: String = "1".repeat(24),
        path: String = "0",
        text: String = "گزینه",
        checked: Boolean = false,
        enabled: Boolean = true,
    ): AccessibilityNodeSnapshot = AccessibilityNodeSnapshot(
        nodeId = id,
        path = path,
        depth = path.count { it == '.' },
        windowId = 1,
        packageName = PACKAGE_NAME,
        className = "android.widget.CheckBox",
        viewId = VIEW_ID,
        text = text,
        bounds = ScreenBounds(0, 0, 100, 100),
        semanticFingerprint = id,
        childCount = 0,
        inputType = 0,
        clickable = true,
        longClickable = false,
        focusable = true,
        focused = false,
        editable = false,
        scrollable = false,
        enabled = enabled,
        selected = false,
        checkable = true,
        checked = checked,
        visibleToUser = true,
        accessibilityFocused = false,
        password = false,
        heading = false,
        actions = emptyList(),
    )

    private companion object {
        const val PACKAGE_NAME = "com.example"
        const val VIEW_ID = "com.example:id/checkbox"
    }
}
