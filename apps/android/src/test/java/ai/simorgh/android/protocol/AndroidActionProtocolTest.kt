package ai.simorgh.android.protocol

import ai.simorgh.android.actions.ActionOutcome
import ai.simorgh.android.actions.ActivePackageEqualsPredicate
import ai.simorgh.android.actions.AndroidActionCommand
import ai.simorgh.android.actions.AndroidActionContractValidator
import ai.simorgh.android.actions.AndroidActionResult
import ai.simorgh.android.actions.AndroidVerificationPolicy
import ai.simorgh.android.actions.ObservationPrecondition
import ai.simorgh.android.actions.OpenAppOperation
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.encodeToJsonElement
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Test

class AndroidActionProtocolTest {
    @Test
    fun `action command decoder preserves typed operation and envelope identity`() {
        val command = command()
        val envelope = ProtocolEnvelope(
            messageId = COMMAND_ENVELOPE_ID,
            type = DeviceProtocol.TYPE_ACTION_COMMAND,
            sentAtMs = 1_000,
            deviceId = DEVICE_ID,
            payload = DeviceProtocol.json.encodeToJsonElement(command).jsonObject,
        )

        val decodedEnvelope = DeviceProtocol.decode(DeviceProtocol.encode(envelope))
        val decodedCommand = DeviceProtocol.decodeActionCommand(decodedEnvelope)

        assertEquals(COMMAND_ENVELOPE_ID, decodedEnvelope.messageId)
        assertEquals(DEVICE_ID, decodedEnvelope.deviceId)
        assertEquals(command, decodedCommand)
        assertEquals("com.example", (decodedCommand.operation as OpenAppOperation).packageName)
    }

    @Test
    fun `command acknowledgement correlates to the original command envelope`() {
        val command = command()
        val acknowledgement = DeviceProtocol.actionCommandAck(
            deviceId = DEVICE_ID,
            commandEnvelopeId = COMMAND_ENVELOPE_ID,
            command = command,
            status = ActionCommandAckStatus.ACCEPTED,
            detail = "accepted by fixture",
            nowMs = 2_000,
        )

        val payload = DeviceProtocol.json.decodeFromJsonElement(
            DeviceActionCommandAckPayload.serializer(),
            acknowledgement.payload,
        )

        assertEquals(DeviceProtocol.TYPE_ACTION_COMMAND_ACK, acknowledgement.type)
        assertEquals(COMMAND_ENVELOPE_ID, acknowledgement.correlationId)
        assertEquals(command.commandId, payload.commandId)
        assertEquals(command.actionId, payload.actionId)
        assertEquals(ActionCommandAckStatus.ACCEPTED, payload.status)
    }

    @Test
    fun `action result keeps stable message id and command correlation`() {
        val result = result()
        val envelope = DeviceProtocol.actionResult(
            deviceId = DEVICE_ID,
            commandEnvelopeId = COMMAND_ENVELOPE_ID,
            result = result,
            messageId = RESULT_MESSAGE_ID,
            nowMs = 3_000,
        )

        val payload = DeviceProtocol.json.decodeFromJsonElement(
            AndroidActionResult.serializer(),
            envelope.payload,
        )

        assertEquals(DeviceProtocol.TYPE_ACTION_RESULT, envelope.type)
        assertEquals(RESULT_MESSAGE_ID, envelope.messageId)
        assertEquals(COMMAND_ENVELOPE_ID, envelope.correlationId)
        assertEquals(result, payload)
    }

    @Test
    fun `result acknowledgement decoder and cancellation decoder are strict and typed`() {
        val resultAcknowledgement = DeviceActionResultAckPayload(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            status = ActionResultAckStatus.ACCEPTED,
            receivedAtMs = 4_000,
        )
        val resultAckEnvelope = ProtocolEnvelope(
            messageId = RESULT_ACK_MESSAGE_ID,
            type = DeviceProtocol.TYPE_ACTION_RESULT_ACK,
            sentAtMs = 4_000,
            deviceId = DEVICE_ID,
            correlationId = RESULT_MESSAGE_ID,
            payload = DeviceProtocol.json.encodeToJsonElement(resultAcknowledgement).jsonObject,
        )
        val cancellation = DeviceActionCancelPayload(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            reason = "fixture cancellation",
        )
        val cancellationEnvelope = ProtocolEnvelope(
            messageId = CANCEL_MESSAGE_ID,
            type = DeviceProtocol.TYPE_ACTION_CANCEL,
            sentAtMs = 5_000,
            deviceId = DEVICE_ID,
            correlationId = COMMAND_ENVELOPE_ID,
            payload = DeviceProtocol.json.encodeToJsonElement(cancellation).jsonObject,
        )

        assertEquals(
            resultAcknowledgement,
            DeviceProtocol.decodeActionResultAck(
                DeviceProtocol.decode(DeviceProtocol.encode(resultAckEnvelope)),
            ),
        )
        assertEquals(
            cancellation,
            DeviceProtocol.decodeActionCancel(
                DeviceProtocol.decode(DeviceProtocol.encode(cancellationEnvelope)),
            ),
        )
    }

    @Test
    fun `cancellation acknowledgement correlates to the cancel message not the command`() {
        val cancellation = DeviceActionCancelPayload(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            reason = "fixture cancellation",
        )
        val acknowledgement = DeviceProtocol.actionCancelAck(
            deviceId = DEVICE_ID,
            cancelEnvelopeId = CANCEL_MESSAGE_ID,
            cancellation = cancellation,
            status = ActionCancelAckStatus.ACCEPTED,
            nowMs = 6_000,
        )
        val payload = DeviceProtocol.json.decodeFromJsonElement(
            DeviceActionCancelAckPayload.serializer(),
            acknowledgement.payload,
        )

        assertEquals(DeviceProtocol.TYPE_ACTION_CANCEL_ACK, acknowledgement.type)
        assertEquals(CANCEL_MESSAGE_ID, acknowledgement.correlationId)
        assertEquals(COMMAND_ID, payload.commandId)
        assertEquals(ACTION_ID, payload.actionId)
        assertEquals(ActionCancelAckStatus.ACCEPTED, payload.status)
    }

    private fun command(): AndroidActionCommand = AndroidActionContractValidator.validate(
        AndroidActionCommand(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            issuedAtMs = 500,
            deadlineAtMs = 60_500,
            precondition = ObservationPrecondition(),
            operation = OpenAppOperation(packageName = "com.example"),
            verification = AndroidVerificationPolicy(
                predicates = listOf(ActivePackageEqualsPredicate("com.example")),
            ),
        ),
    )

    private fun result(): AndroidActionResult = AndroidActionContractValidator.validate(
        AndroidActionResult(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            outcome = ActionOutcome.SUCCEEDED,
            startedAtMs = 1_000,
            finishedAtMs = 1_001,
            detail = "fixture completed",
        ),
    )

    private companion object {
        const val DEVICE_ID = "11111111-1111-1111-1111-111111111111"
        const val COMMAND_ENVELOPE_ID = "22222222-2222-2222-2222-222222222222"
        const val COMMAND_ID = "33333333-3333-3333-3333-333333333333"
        const val ACTION_ID = "44444444-4444-4444-4444-444444444444"
        const val RESULT_MESSAGE_ID = "55555555-5555-5555-5555-555555555555"
        const val RESULT_ACK_MESSAGE_ID = "66666666-6666-6666-6666-666666666666"
        const val CANCEL_MESSAGE_ID = "77777777-7777-7777-7777-777777777777"
    }
}
