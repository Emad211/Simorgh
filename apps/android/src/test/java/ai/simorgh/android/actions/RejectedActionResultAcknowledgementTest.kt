package ai.simorgh.android.actions

import ai.simorgh.android.protocol.ActionCommandAckStatus
import ai.simorgh.android.protocol.ActionResultAckStatus
import ai.simorgh.android.protocol.DeviceActionResultAckPayload
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class RejectedActionResultAcknowledgementTest {
    @Test
    fun `Core rejected result remains unacknowledged and blocks the next action`() {
        val ledger = InMemoryLedger()
        val handler = ImmediateSuccessHandler()
        val deliveries = mutableListOf<PendingActionResultDelivery>()
        val router = AndroidActionRouter(
            ledger = ledger,
            handlerProvider = { handler },
            resultEmitter = deliveries::add,
            nowMillis = { NOW_MS },
        )
        val first = command(COMMAND_ID, ACTION_ID)

        assertEquals(
            ActionCommandAckStatus.ACCEPTED,
            router.receiveCommand(COMMAND_ENVELOPE_ID, first).status,
        )
        val delivery = deliveries.single()

        assertFalse(
            router.acknowledgeResult(
                acknowledgement = DeviceActionResultAckPayload(
                    commandId = first.commandId,
                    actionId = first.actionId,
                    status = ActionResultAckStatus.REJECTED,
                    receivedAtMs = NOW_MS + 10,
                    detail = "Core could not verify result evidence",
                ),
                correlationId = delivery.resultMessageId,
            ),
        )

        val persisted = (ledger.load() as ActionLedgerLoadResult.Loaded).entry
        assertFalse(persisted.resultAcknowledged)
        assertEquals(
            ActionCommandAckStatus.BUSY,
            router.receiveCommand(
                SECOND_COMMAND_ENVELOPE_ID,
                command(SECOND_COMMAND_ID, SECOND_ACTION_ID),
            ).status,
        )
    }

    private fun command(commandId: String, actionId: String): AndroidActionCommand =
        AndroidActionContractValidator.validate(
            AndroidActionCommand(
                commandId = commandId,
                actionId = actionId,
                issuedAtMs = NOW_MS - 1_000,
                deadlineAtMs = NOW_MS + 60_000,
                precondition = ObservationPrecondition(),
                operation = OpenAppOperation(packageName = PACKAGE_NAME),
                verification = AndroidVerificationPolicy(
                    predicates = listOf(ActivePackageEqualsPredicate(PACKAGE_NAME)),
                ),
            ),
        )

    private class ImmediateSuccessHandler : AndroidActionHandler {
        override fun submit(
            request: ReceivedAndroidAction,
            completion: AndroidActionCompletion,
        ): Boolean {
            completion.complete(
                AndroidActionContractValidator.validate(
                    AndroidActionResult(
                        commandId = request.command.commandId,
                        actionId = request.command.actionId,
                        outcome = ActionOutcome.SUCCEEDED,
                        failureCode = ActionFailureCode.NONE,
                        startedAtMs = NOW_MS,
                        finishedAtMs = NOW_MS + 1,
                        attempts = 0,
                    ),
                ),
            )
            return true
        }

        override fun cancel(commandId: String, actionId: String, reason: String): Boolean = false
    }

    private class InMemoryLedger : ActionLedger {
        private var state: ActionLedgerLoadResult = ActionLedgerLoadResult.Empty

        override fun load(): ActionLedgerLoadResult = state

        override fun save(entry: PersistedActionEntry) {
            state = ActionLedgerLoadResult.Loaded(entry.validated())
        }

        override fun clear() {
            state = ActionLedgerLoadResult.Empty
        }
    }

    private companion object {
        const val NOW_MS = 10_000L
        const val PACKAGE_NAME = "com.example"
        const val COMMAND_ENVELOPE_ID = "11111111-1111-1111-1111-111111111111"
        const val SECOND_COMMAND_ENVELOPE_ID = "22222222-2222-2222-2222-222222222222"
        const val COMMAND_ID = "33333333-3333-3333-3333-333333333333"
        const val ACTION_ID = "44444444-4444-4444-4444-444444444444"
        const val SECOND_COMMAND_ID = "55555555-5555-5555-5555-555555555555"
        const val SECOND_ACTION_ID = "66666666-6666-6666-6666-666666666666"
    }
}
