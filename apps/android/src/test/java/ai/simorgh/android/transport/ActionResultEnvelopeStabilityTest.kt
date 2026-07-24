package ai.simorgh.android.transport

import ai.simorgh.android.actions.ActionOutcome
import ai.simorgh.android.actions.AndroidActionContractValidator
import ai.simorgh.android.actions.AndroidActionResult
import ai.simorgh.android.actions.PendingActionResultDelivery
import ai.simorgh.android.protocol.ProtocolEnvelope
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.ArrayDeque

class ActionResultEnvelopeStabilityTest {
    @Test
    fun `same persisted result reconstructs the same envelope after recovery`() {
        val scheduler = QueueObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val publisher = ActionResultPublisher(
            deviceId = DEVICE_ID,
            sender = { envelope -> sent += envelope; true },
            scheduler = scheduler,
        )
        val pending = PendingActionResultDelivery(
            commandEnvelopeId = COMMAND_ENVELOPE_ID,
            resultMessageId = RESULT_MESSAGE_ID,
            result = result(),
        )

        assertTrue(publisher.submit(pending))
        assertTrue(publisher.submit(pending))
        publisher.setConnected(true)
        scheduler.runNext()

        val envelope = sent.single()
        assertEquals(RESULT_MESSAGE_ID, envelope.messageId)
        assertEquals(COMMAND_ENVELOPE_ID, envelope.correlationId)
        assertEquals(RESULT_FINISHED_AT_MS, envelope.sentAtMs)
        publisher.close()
    }

    private fun result(): AndroidActionResult = AndroidActionContractValidator.validate(
        AndroidActionResult(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            outcome = ActionOutcome.SUCCEEDED,
            startedAtMs = RESULT_FINISHED_AT_MS - 1,
            finishedAtMs = RESULT_FINISHED_AT_MS,
            detail = "fixture completed",
        ),
    )

    private class QueueObservationScheduler : ObservationScheduler {
        private val tasks = ArrayDeque<QueuedTask>()

        override fun nowMillis(): Long = 0

        override fun schedule(delayMillis: Long, task: () -> Unit): ScheduledObservationTask {
            val queued = QueuedTask(action = task)
            tasks.addLast(queued)
            return ScheduledObservationTask { queued.cancelled = true }
        }

        fun runNext() {
            while (tasks.isNotEmpty()) {
                val next = tasks.removeFirst()
                if (!next.cancelled) {
                    next.action()
                    return
                }
            }
            error("no scheduled task was available")
        }

        override fun close() {
            tasks.clear()
        }

        private data class QueuedTask(
            val action: () -> Unit,
            var cancelled: Boolean = false,
        )
    }

    private companion object {
        const val DEVICE_ID = "11111111-1111-1111-1111-111111111111"
        const val COMMAND_ENVELOPE_ID = "22222222-2222-2222-2222-222222222222"
        const val COMMAND_ID = "33333333-3333-3333-3333-333333333333"
        const val ACTION_ID = "44444444-4444-4444-4444-444444444444"
        const val RESULT_MESSAGE_ID = "55555555-5555-5555-5555-555555555555"
        const val RESULT_FINISHED_AT_MS = 5_000L
    }
}
