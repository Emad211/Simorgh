package ai.simorgh.android.transport

import ai.simorgh.android.actions.ActionOutcome
import ai.simorgh.android.actions.AndroidActionContractValidator
import ai.simorgh.android.actions.AndroidActionResult
import ai.simorgh.android.actions.PendingActionResultDelivery
import ai.simorgh.android.protocol.ActionResultAckStatus
import ai.simorgh.android.protocol.DeviceActionResultAckPayload
import ai.simorgh.android.protocol.DeviceProtocol
import ai.simorgh.android.protocol.ProtocolEnvelope
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.PriorityQueue

class ActionResultPublisherTest {
    @Test
    fun `publisher preserves result message and command correlation until matching ack`() {
        val scheduler = ManualObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val publisher = publisher(
            scheduler = scheduler,
            sender = { envelope -> sent += envelope; true },
        )
        val pending = pendingResult()

        publisher.setConnected(true)
        assertTrue(publisher.submit(pending))
        scheduler.runCurrent()

        val envelope = sent.single()
        assertEquals(DeviceProtocol.TYPE_ACTION_RESULT, envelope.type)
        assertEquals(RESULT_MESSAGE_ID, envelope.messageId)
        assertEquals(COMMAND_ENVELOPE_ID, envelope.correlationId)
        assertEquals(ACTION_ID, publisher.pendingActionId())

        assertTrue(
            publisher.acknowledge(
                acknowledgement = resultAck(ActionResultAckStatus.ACCEPTED),
                correlationId = RESULT_MESSAGE_ID,
            ),
        )
        assertNull(publisher.pendingActionId())
        publisher.close()
    }

    @Test
    fun `ack timeout retries the exact envelope three times then pauses`() {
        val scheduler = ManualObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val events = mutableListOf<String>()
        val publisher = ActionResultPublisher(
            deviceId = DEVICE_ID,
            sender = { envelope -> sent += envelope; true },
            listener = events::add,
            scheduler = scheduler,
            acknowledgementTimeoutMillis = 100,
            maximumAttemptsPerConnection = 3,
        )

        publisher.setConnected(true)
        publisher.submit(pendingResult())
        scheduler.runCurrent()
        scheduler.advanceBy(300)

        assertEquals(3, sent.size)
        assertEquals(1, sent.map(ProtocolEnvelope::messageId).distinct().size)
        assertEquals(1, sent.map(ProtocolEnvelope::correlationId).distinct().size)
        assertEquals(ACTION_ID, publisher.pendingActionId())
        assertTrue(events.last().contains("paused after 3 attempts"))
        publisher.close()
    }

    @Test
    fun `failed socket send does not consume an attempt and resumes on reconnect`() {
        val scheduler = ManualObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        var sendIsAvailable = false
        val publisher = publisher(
            scheduler = scheduler,
            sender = { envelope ->
                if (sendIsAvailable) {
                    sent += envelope
                    true
                } else {
                    false
                }
            },
        )

        publisher.setConnected(true)
        publisher.submit(pendingResult())
        scheduler.runCurrent()
        assertTrue(sent.isEmpty())
        assertEquals(ACTION_ID, publisher.pendingActionId())

        sendIsAvailable = true
        publisher.setConnected(true)
        scheduler.runCurrent()

        assertEquals(1, sent.size)
        assertEquals(RESULT_MESSAGE_ID, sent.single().messageId)
        publisher.close()
    }

    @Test
    fun `mismatched acknowledgement and competing result cannot clear or replace delivery`() {
        val scheduler = ManualObservationScheduler()
        val sent = mutableListOf<ProtocolEnvelope>()
        val publisher = publisher(
            scheduler = scheduler,
            sender = { envelope -> sent += envelope; true },
        )
        publisher.setConnected(true)
        publisher.submit(pendingResult())
        scheduler.runCurrent()

        assertFalse(
            publisher.acknowledge(
                acknowledgement = resultAck(ActionResultAckStatus.ACCEPTED),
                correlationId = WRONG_MESSAGE_ID,
            ),
        )
        assertFalse(
            publisher.submit(
                pendingResult(
                    actionId = SECOND_ACTION_ID,
                    resultMessageId = SECOND_RESULT_MESSAGE_ID,
                ),
            ),
        )
        assertEquals(ACTION_ID, publisher.pendingActionId())
        assertEquals(1, sent.size)
        publisher.close()
    }

    private fun publisher(
        scheduler: ManualObservationScheduler,
        sender: (ProtocolEnvelope) -> Boolean,
    ): ActionResultPublisher = ActionResultPublisher(
        deviceId = DEVICE_ID,
        sender = sender,
        scheduler = scheduler,
        acknowledgementTimeoutMillis = 1_000,
        maximumAttemptsPerConnection = 3,
    )

    private fun pendingResult(
        actionId: String = ACTION_ID,
        resultMessageId: String = RESULT_MESSAGE_ID,
    ): PendingActionResultDelivery = PendingActionResultDelivery(
        commandEnvelopeId = COMMAND_ENVELOPE_ID,
        resultMessageId = resultMessageId,
        result = AndroidActionContractValidator.validate(
            AndroidActionResult(
                commandId = COMMAND_ID,
                actionId = actionId,
                outcome = ActionOutcome.SUCCEEDED,
                startedAtMs = 1_000,
                finishedAtMs = 1_001,
                detail = "fixture completed",
            ),
        ),
    )

    private fun resultAck(status: ActionResultAckStatus): DeviceActionResultAckPayload =
        DeviceActionResultAckPayload(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            status = status,
            receivedAtMs = 2_000,
        )

    private class ManualObservationScheduler : ObservationScheduler {
        private val tasks = PriorityQueue<ScheduledTask>(
            compareBy<ScheduledTask> { it.dueAtMillis }.thenBy { it.sequence },
        )
        private var nextSequence = 0L
        private var currentTimeMillis = 0L

        override fun nowMillis(): Long = currentTimeMillis

        override fun schedule(delayMillis: Long, task: () -> Unit): ScheduledObservationTask {
            val scheduled = ScheduledTask(
                dueAtMillis = currentTimeMillis + delayMillis.coerceAtLeast(0),
                sequence = nextSequence++,
                action = task,
            )
            tasks += scheduled
            return ScheduledObservationTask { scheduled.cancelled = true }
        }

        fun runCurrent() {
            runUntil(currentTimeMillis)
        }

        fun advanceBy(milliseconds: Long) {
            require(milliseconds >= 0)
            runUntil(currentTimeMillis + milliseconds)
        }

        private fun runUntil(targetTimeMillis: Long) {
            while (true) {
                val next = tasks.peek() ?: break
                if (next.dueAtMillis > targetTimeMillis) {
                    break
                }
                tasks.remove()
                currentTimeMillis = next.dueAtMillis
                if (!next.cancelled) {
                    next.action()
                }
            }
            currentTimeMillis = targetTimeMillis
        }

        override fun close() {
            tasks.clear()
        }

        private data class ScheduledTask(
            val dueAtMillis: Long,
            val sequence: Long,
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
        const val WRONG_MESSAGE_ID = "66666666-6666-6666-6666-666666666666"
        const val SECOND_ACTION_ID = "77777777-7777-7777-7777-777777777777"
        const val SECOND_RESULT_MESSAGE_ID = "88888888-8888-8888-8888-888888888888"
    }
}
