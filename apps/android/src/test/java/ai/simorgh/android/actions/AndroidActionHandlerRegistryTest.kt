package ai.simorgh.android.actions

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidActionHandlerRegistryTest {
    @Test
    fun `handler exception becomes a blocked result instead of a rejected replayable command`() {
        val throwingHandler = object : AndroidActionHandler {
            override fun submit(
                request: ReceivedAndroidAction,
                completion: AndroidActionCompletion,
            ): Boolean = throw IllegalStateException("fixture failure")

            override fun cancel(commandId: String, actionId: String, reason: String): Boolean = false
        }
        val installation = AndroidActionHandlerRegistry.install(throwingHandler)
        try {
            var result: AndroidActionResult? = null
            val accepted = requireNotNull(AndroidActionHandlerRegistry.current()).submit(
                request = ReceivedAndroidAction(
                    commandEnvelopeId = COMMAND_ENVELOPE_ID,
                    command = command(),
                ),
                completion = AndroidActionCompletion { completed -> result = completed },
            )

            assertTrue(accepted)
            assertNotNull(result)
            assertEquals(ActionOutcome.BLOCKED, result?.outcome)
            assertEquals(ActionFailureCode.INTERNAL_ERROR, result?.failureCode)
            assertEquals(0, result?.attempts)
            assertTrue(result?.detail.orEmpty().contains("will not be replayed"))
        } finally {
            installation.close()
        }
    }

    @Test
    fun `registry exposes only one installed handler and removes the guarded instance on close`() {
        val handler = object : AndroidActionHandler {
            override fun submit(
                request: ReceivedAndroidAction,
                completion: AndroidActionCompletion,
            ): Boolean = false

            override fun cancel(commandId: String, actionId: String, reason: String): Boolean = false
        }
        val installation = AndroidActionHandlerRegistry.install(handler)
        try {
            assertNotNull(AndroidActionHandlerRegistry.current())
        } finally {
            installation.close()
        }
        assertEquals(null, AndroidActionHandlerRegistry.current())
    }

    private fun command(): AndroidActionCommand = AndroidActionContractValidator.validate(
        AndroidActionCommand(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            issuedAtMs = 1_000,
            deadlineAtMs = 61_000,
            precondition = ObservationPrecondition(),
            operation = OpenAppOperation(packageName = "com.example"),
            verification = AndroidVerificationPolicy(
                predicates = listOf(ActivePackageEqualsPredicate("com.example")),
            ),
        ),
    )

    private companion object {
        const val COMMAND_ENVELOPE_ID = "11111111-1111-1111-1111-111111111111"
        const val COMMAND_ID = "22222222-2222-2222-2222-222222222222"
        const val ACTION_ID = "33333333-3333-3333-3333-333333333333"
    }
}
