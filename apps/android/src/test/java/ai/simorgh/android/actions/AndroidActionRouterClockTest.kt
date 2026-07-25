package ai.simorgh.android.actions

import ai.simorgh.android.protocol.ActionCommandAckStatus
import ai.simorgh.android.time.CoreClock
import ai.simorgh.android.time.CoreClockReading
import ai.simorgh.android.time.CoreDeadlineBudget
import ai.simorgh.android.time.CoreDeadlineUnavailableReason
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.atomic.AtomicInteger

class AndroidActionRouterClockTest {
    @Test
    fun `unavailable Core clock rejects before ledger ownership or handler submission`() {
        val ledger = RecordingLedger()
        val submitCount = AtomicInteger(0)
        val router = AndroidActionRouter(
            ledger = ledger,
            handlerProvider = {
                RecordingHandler {
                    submitCount.incrementAndGet()
                    true
                }
            },
            resultEmitter = {},
            coreClock = UnavailableClock(
                CoreDeadlineUnavailableReason.CLOCK_UNAVAILABLE,
                "registration clock sample is unavailable",
            ),
        )

        val receipt = router.receiveCommand(COMMAND_ENVELOPE_ID, command())

        assertEquals(ActionCommandAckStatus.REJECTED, receipt.status)
        assertTrue(receipt.detail.contains("clock", ignoreCase = true))
        assertEquals(ActionLedgerLoadResult.Empty, ledger.load())
        assertEquals(0, submitCount.get())
    }

    @Test
    fun `expired bounded Core deadline maps to expired command acknowledgement`() {
        val ledger = RecordingLedger()
        val router = AndroidActionRouter(
            ledger = ledger,
            handlerProvider = { RecordingHandler { true } },
            resultEmitter = {},
            coreClock = UnavailableClock(
                CoreDeadlineUnavailableReason.EXPIRED,
                "bounded Core deadline elapsed",
            ),
        )

        val receipt = router.receiveCommand(COMMAND_ENVELOPE_ID, command())

        assertEquals(ActionCommandAckStatus.EXPIRED, receipt.status)
        assertEquals(ActionLedgerLoadResult.Empty, ledger.load())
    }

    @Test
    fun `uncertainty rejects command instead of accepting an unsafe short budget`() {
        val ledger = RecordingLedger()
        val router = AndroidActionRouter(
            ledger = ledger,
            handlerProvider = { RecordingHandler { true } },
            resultEmitter = {},
            coreClock = UnavailableClock(
                CoreDeadlineUnavailableReason.UNCERTAINTY,
                "clock uncertainty consumes the remaining command deadline budget",
            ),
        )

        val receipt = router.receiveCommand(COMMAND_ENVELOPE_ID, command())

        assertEquals(ActionCommandAckStatus.REJECTED, receipt.status)
        assertTrue(receipt.detail.contains("uncertainty"))
        assertEquals(ActionLedgerLoadResult.Empty, ledger.load())
    }

    @Test
    fun `exact active duplicate remains duplicate when later clock estimate disappears`() {
        val ledger = RecordingLedger()
        val clock = MutableClock()
        val handler = RecordingHandler { true }
        val router = AndroidActionRouter(
            ledger = ledger,
            handlerProvider = { handler },
            resultEmitter = {},
            coreClock = clock,
        )
        val command = command()

        val accepted = router.receiveCommand(COMMAND_ENVELOPE_ID, command)
        clock.available = false
        val duplicate = router.receiveCommand(COMMAND_ENVELOPE_ID, command)

        assertEquals(ActionCommandAckStatus.ACCEPTED, accepted.status)
        assertEquals(ActionCommandAckStatus.DUPLICATE, duplicate.status)
        assertEquals(1, handler.submitCount)
        assertTrue(ledger.load() is ActionLedgerLoadResult.Loaded)
    }

    private fun command(): AndroidActionCommand = AndroidActionContractValidator.validate(
        AndroidActionCommand(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            issuedAtMs = CORE_NOW_MS - 1_000,
            deadlineAtMs = CORE_NOW_MS + 60_000,
            precondition = ObservationPrecondition(),
            operation = OpenAppOperation(packageName = PACKAGE_NAME),
            verification = AndroidVerificationPolicy(
                predicates = listOf(ActivePackageEqualsPredicate(PACKAGE_NAME)),
            ),
        ),
    )

    private class RecordingLedger : ActionLedger {
        private var value: ActionLedgerLoadResult = ActionLedgerLoadResult.Empty

        override fun load(): ActionLedgerLoadResult = value

        override fun save(entry: PersistedActionEntry) {
            value = ActionLedgerLoadResult.Loaded(entry.validated())
        }

        override fun clear() {
            value = ActionLedgerLoadResult.Empty
        }
    }

    private class RecordingHandler(
        private val submitResult: () -> Boolean,
    ) : AndroidActionHandler {
        var submitCount: Int = 0
            private set

        override fun submit(
            request: ReceivedAndroidAction,
            completion: AndroidActionCompletion,
        ): Boolean {
            submitCount += 1
            return submitResult()
        }

        override fun cancel(commandId: String, actionId: String, reason: String): Boolean = false
    }

    private class UnavailableClock(
        private val kind: CoreDeadlineUnavailableReason,
        private val detail: String,
    ) : CoreClock {
        override fun elapsedRealtimeMs(): Long = ELAPSED_NOW_MS

        override fun reading(): CoreClockReading? = null

        override fun deadlineBudget(deadlineCoreTimeMs: Long): CoreDeadlineBudget =
            CoreDeadlineBudget.Unavailable(
                kind = kind,
                reason = detail,
            )
    }

    private class MutableClock : CoreClock {
        var available: Boolean = true

        override fun elapsedRealtimeMs(): Long = ELAPSED_NOW_MS

        override fun reading(): CoreClockReading? = if (available) readingValue() else null

        override fun deadlineBudget(deadlineCoreTimeMs: Long): CoreDeadlineBudget {
            if (!available) {
                return CoreDeadlineBudget.Unavailable(
                    kind = CoreDeadlineUnavailableReason.CLOCK_UNAVAILABLE,
                    reason = "clock estimate disappeared",
                )
            }
            val reading = readingValue()
            return CoreDeadlineBudget.Available(
                guaranteedRemainingMs = deadlineCoreTimeMs - reading.latestCoreTimeMs,
                reading = reading,
            )
        }

        private fun readingValue(): CoreClockReading = CoreClockReading(
            generation = 1,
            estimatedCoreTimeMs = CORE_NOW_MS,
            earliestCoreTimeMs = CORE_NOW_MS,
            latestCoreTimeMs = CORE_NOW_MS,
            uncertaintyMs = 0,
            sampleAgeMs = 0,
            lastRoundTripTimeMs = 0,
            sampleCount = 1,
            discontinuityCount = 0,
            wallClockJumpCount = 0,
            observedAtElapsedRealtimeMs = ELAPSED_NOW_MS,
        )
    }

    private companion object {
        const val CORE_NOW_MS = 100_000L
        const val ELAPSED_NOW_MS = 5_000L
        const val PACKAGE_NAME = "com.example.target"
        const val COMMAND_ENVELOPE_ID = "11111111-1111-1111-1111-111111111111"
        const val COMMAND_ID = "22222222-2222-2222-2222-222222222222"
        const val ACTION_ID = "33333333-3333-3333-3333-333333333333"
    }
}
