package ai.simorgh.android.actions

import ai.simorgh.android.protocol.ActionCommandAckStatus
import ai.simorgh.android.protocol.ActionResultAckStatus
import ai.simorgh.android.protocol.DeviceActionResultAckPayload
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidActionRouterTest {
    @Test
    fun `ledger is active before handler submission and an active duplicate is not submitted twice`() {
        val ledger = InMemoryActionLedger()
        var ledgerWasActiveAtSubmit = false
        val handler = RecordingActionHandler { _, _ ->
            ledgerWasActiveAtSubmit =
                (ledger.load() as? ActionLedgerLoadResult.Loaded)?.entry?.phase ==
                ActionLedgerPhase.ACTIVE
            true
        }
        val router = router(ledger = ledger, handler = handler)
        val command = command()

        val first = router.receiveCommand(COMMAND_ENVELOPE_ID, command)
        val duplicate = router.receiveCommand(COMMAND_ENVELOPE_ID, command)

        assertEquals(ActionCommandAckStatus.ACCEPTED, first.status)
        assertEquals(ActionCommandAckStatus.DUPLICATE, duplicate.status)
        assertTrue(ledgerWasActiveAtSubmit)
        assertEquals(1, handler.submitCount)
    }

    @Test
    fun `synchronous completion is preserved even when handler returns rejected`() {
        val ledger = InMemoryActionLedger()
        val deliveries = mutableListOf<PendingActionResultDelivery>()
        val command = command()
        val handler = RecordingActionHandler { request, completion ->
            completion.complete(successResult(request.command))
            false
        }
        val router = router(
            ledger = ledger,
            handler = handler,
            deliveries = deliveries,
        )

        val receipt = router.receiveCommand(COMMAND_ENVELOPE_ID, command)
        val persisted = (ledger.load() as ActionLedgerLoadResult.Loaded).entry

        assertEquals(ActionCommandAckStatus.ACCEPTED, receipt.status)
        assertEquals(ActionLedgerPhase.COMPLETED, persisted.phase)
        assertEquals(ActionOutcome.SUCCEEDED, persisted.result?.outcome)
        assertEquals(2, deliveries.size)
        assertEquals(1, deliveries.map(PendingActionResultDelivery::resultMessageId).distinct().size)
        assertEquals(persisted.resultMessageId, deliveries.first().resultMessageId)
    }

    @Test
    fun `process restart blocks uncertain active execution instead of replaying the side effect`() {
        val ledger = InMemoryActionLedger()
        val originalHandler = RecordingActionHandler { _, _ -> true }
        val command = command()
        router(ledger = ledger, handler = originalHandler)
            .receiveCommand(COMMAND_ENVELOPE_ID, command)

        val recoveredDeliveries = mutableListOf<PendingActionResultDelivery>()
        val replacementHandler = RecordingActionHandler { _, _ -> true }
        val recoveredRouter = router(
            ledger = ledger,
            handler = replacementHandler,
            deliveries = recoveredDeliveries,
        )

        val receipt = recoveredRouter.receiveCommand(COMMAND_ENVELOPE_ID, command)
        val result = recoveredDeliveries.single().result

        assertEquals(ActionCommandAckStatus.DUPLICATE, receipt.status)
        assertEquals(0, replacementHandler.submitCount)
        assertEquals(ActionOutcome.BLOCKED, result.outcome)
        assertEquals(ActionFailureCode.INTERNAL_ERROR, result.failureCode)
        assertEquals(0, result.attempts)
        assertTrue(result.detail.contains("was not re-executed"))
    }

    @Test
    fun `unacknowledged result blocks a new command until the matching result ack is persisted`() {
        val ledger = InMemoryActionLedger()
        val deliveries = mutableListOf<PendingActionResultDelivery>()
        val handler = RecordingActionHandler { request, completion ->
            completion.complete(successResult(request.command))
            true
        }
        val router = router(
            ledger = ledger,
            handler = handler,
            deliveries = deliveries,
        )
        val firstCommand = command()
        router.receiveCommand(COMMAND_ENVELOPE_ID, firstCommand)

        val blocked = router.receiveCommand(
            SECOND_COMMAND_ENVELOPE_ID,
            command(
                commandId = SECOND_COMMAND_ID,
                actionId = SECOND_ACTION_ID,
            ),
        )
        val firstDelivery = deliveries.first()
        val acknowledgement = DeviceActionResultAckPayload(
            commandId = firstCommand.commandId,
            actionId = firstCommand.actionId,
            status = ActionResultAckStatus.ACCEPTED,
            receivedAtMs = NOW_MS + 10,
        )

        assertEquals(ActionCommandAckStatus.BUSY, blocked.status)
        assertEquals(2, deliveries.size)
        assertEquals(1, deliveries.map(PendingActionResultDelivery::resultMessageId).distinct().size)
        assertTrue(
            router.acknowledgeResult(
                acknowledgement = acknowledgement,
                correlationId = firstDelivery.resultMessageId,
            ),
        )

        val accepted = router.receiveCommand(
            SECOND_COMMAND_ENVELOPE_ID,
            command(
                commandId = SECOND_COMMAND_ID,
                actionId = SECOND_ACTION_ID,
            ),
        )
        assertEquals(ActionCommandAckStatus.ACCEPTED, accepted.status)
        assertEquals(2, handler.submitCount)
    }

    @Test
    fun `mismatched result acknowledgement cannot release the ledger`() {
        val ledger = InMemoryActionLedger()
        val deliveries = mutableListOf<PendingActionResultDelivery>()
        val handler = RecordingActionHandler { request, completion ->
            completion.complete(successResult(request.command))
            true
        }
        val router = router(
            ledger = ledger,
            handler = handler,
            deliveries = deliveries,
        )
        val command = command()
        router.receiveCommand(COMMAND_ENVELOPE_ID, command)

        val accepted = router.acknowledgeResult(
            acknowledgement = DeviceActionResultAckPayload(
                commandId = command.commandId,
                actionId = command.actionId,
                status = ActionResultAckStatus.ACCEPTED,
                receivedAtMs = NOW_MS + 10,
            ),
            correlationId = WRONG_RESULT_MESSAGE_ID,
        )

        assertFalse(accepted)
        val persisted = (ledger.load() as ActionLedgerLoadResult.Loaded).entry
        assertFalse(persisted.resultAcknowledged)
    }

    @Test
    fun `corrupt encrypted ledger fails closed before handler invocation`() {
        val handler = RecordingActionHandler { _, _ -> true }
        val router = AndroidActionRouter(
            ledger = CorruptActionLedger(),
            handlerProvider = { handler },
            resultEmitter = {},
            nowMillis = { NOW_MS },
        )

        val receipt = router.receiveCommand(COMMAND_ENVELOPE_ID, command())

        assertEquals(ActionCommandAckStatus.REJECTED, receipt.status)
        assertTrue(receipt.detail.contains("unreadable"))
        assertEquals(0, handler.submitCount)
    }

    private fun router(
        ledger: ActionLedger,
        handler: AndroidActionHandler,
        deliveries: MutableList<PendingActionResultDelivery> = mutableListOf(),
    ): AndroidActionRouter = AndroidActionRouter(
        ledger = ledger,
        handlerProvider = { handler },
        resultEmitter = deliveries::add,
        nowMillis = { NOW_MS },
    )

    private fun command(
        commandId: String = COMMAND_ID,
        actionId: String = ACTION_ID,
    ): AndroidActionCommand = AndroidActionContractValidator.validate(
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

    private fun successResult(command: AndroidActionCommand): AndroidActionResult =
        AndroidActionContractValidator.validate(
            AndroidActionResult(
                commandId = command.commandId,
                actionId = command.actionId,
                outcome = ActionOutcome.SUCCEEDED,
                startedAtMs = NOW_MS,
                finishedAtMs = NOW_MS + 1,
                detail = "fixture completed",
            ),
        )

    private class InMemoryActionLedger : ActionLedger {
        private var state: ActionLedgerLoadResult = ActionLedgerLoadResult.Empty

        override fun load(): ActionLedgerLoadResult = state

        override fun save(entry: PersistedActionEntry) {
            state = ActionLedgerLoadResult.Loaded(entry.validated())
        }

        override fun clear() {
            state = ActionLedgerLoadResult.Empty
        }
    }

    private class CorruptActionLedger : ActionLedger {
        override fun load(): ActionLedgerLoadResult =
            ActionLedgerLoadResult.Corrupt("fixture corruption")

        override fun save(entry: PersistedActionEntry) = error("must not save corrupt ledger")

        override fun clear() = error("must not clear corrupt ledger")
    }

    private class RecordingActionHandler(
        private val onSubmit: (ReceivedAndroidAction, AndroidActionCompletion) -> Boolean,
    ) : AndroidActionHandler {
        var submitCount: Int = 0
            private set

        override fun submit(
            request: ReceivedAndroidAction,
            completion: AndroidActionCompletion,
        ): Boolean {
            submitCount += 1
            return onSubmit(request, completion)
        }

        override fun cancel(commandId: String, actionId: String, reason: String): Boolean = false
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
        const val WRONG_RESULT_MESSAGE_ID = "77777777-7777-7777-7777-777777777777"
    }
}
