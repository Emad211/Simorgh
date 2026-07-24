package ai.simorgh.android.actions

import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidActionContractTest {
    @Test
    fun `typed click command survives strict JSON round trip`() {
        val command = AndroidActionCommand(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            issuedAtMs = 1_000,
            deadlineAtMs = 11_000,
            precondition = ObservationPrecondition(
                expectedStreamId = STREAM_ID,
                minimumSequence = 7,
                expectedStateFingerprint = "a".repeat(64),
                expectedActivePackage = PACKAGE_NAME,
                maximumAgeMs = 2_000,
            ),
            operation = ClickNodeOperation(
                selectors = listOf(selector()),
                allowGestureFallback = true,
            ),
            verification = AndroidVerificationPolicy(
                predicates = listOf(
                    ActivePackageEqualsPredicate(PACKAGE_NAME),
                    NodeExistsPredicate(selector()),
                ),
                timeoutMs = 5_000,
                stableSamples = 2,
            ),
        ).validated()

        val encoded = AndroidActionJson.codec.encodeToString(command)
        val decoded = AndroidActionJson.codec.decodeFromString<AndroidActionCommand>(encoded)

        assertTrue("\"kind\":\"click_node\"" in encoded)
        assertTrue("\"kind\":\"node_exists\"" in encoded)
        assertEquals(command, decoded)
        assertTrue(decoded.operation is ClickNodeOperation)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `selector without identity fields is rejected`() {
        AndroidNodeSelector(packageName = PACKAGE_NAME).validated()
    }

    @Test
    fun `selector automatically requires its strongest signal`() {
        val selector = AndroidNodeSelector(
            packageName = PACKAGE_NAME,
            viewId = VIEW_ID,
            text = TextCriterion("ادامه"),
        ).validated()

        assertEquals(setOf(SelectorField.VIEW_ID), selector.requiredFields)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `command lifetime cannot exceed two minutes`() {
        AndroidActionCommand(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            issuedAtMs = 1_000,
            deadlineAtMs = 121_001,
            precondition = ObservationPrecondition(),
            operation = OpenAppOperation(packageName = PACKAGE_NAME),
            verification = AndroidVerificationPolicy(
                predicates = listOf(ActivePackageEqualsPredicate(PACKAGE_NAME)),
            ),
        ).validated()
    }

    @Test(expected = IllegalArgumentException::class)
    fun `node action requires at least one selector`() {
        AndroidActionCommand(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            issuedAtMs = 1_000,
            deadlineAtMs = 10_000,
            precondition = ObservationPrecondition(),
            operation = ClickNodeOperation(selectors = emptyList()),
            verification = AndroidVerificationPolicy(
                predicates = listOf(ActivePackageEqualsPredicate(PACKAGE_NAME)),
            ),
        ).validated()
    }

    @Test
    fun `failed action result requires a typed failure code`() {
        val result = AndroidActionResult(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            outcome = ActionOutcome.BLOCKED,
            failureCode = ActionFailureCode.TARGET_AMBIGUOUS,
            startedAtMs = 1_000,
            finishedAtMs = 1_020,
            detail = "two candidates had equal scores",
        )

        val encoded = AndroidActionJson.codec.encodeToString(result)
        val decoded = AndroidActionJson.codec.decodeFromString<AndroidActionResult>(encoded)

        assertEquals(ActionFailureCode.TARGET_AMBIGUOUS, decoded.failureCode)
        assertEquals(ActionOutcome.BLOCKED, decoded.outcome)
    }

    private fun selector(): AndroidNodeSelector = AndroidNodeSelector(
        packageName = PACKAGE_NAME,
        viewId = VIEW_ID,
        text = TextCriterion("ادامه"),
        className = "android.widget.Button",
        requiredFields = setOf(SelectorField.VIEW_ID),
        requiredCapabilities = setOf(NodeCapability.CLICKABLE),
    )

    private companion object {
        const val COMMAND_ID = "11111111-1111-1111-1111-111111111111"
        const val ACTION_ID = "22222222-2222-2222-2222-222222222222"
        const val STREAM_ID = "33333333-3333-3333-3333-333333333333"
        const val PACKAGE_NAME = "com.example"
        const val VIEW_ID = "com.example:id/continue_button"
    }
}
