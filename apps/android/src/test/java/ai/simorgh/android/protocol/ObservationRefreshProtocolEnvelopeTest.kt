package ai.simorgh.android.protocol

import kotlinx.serialization.json.encodeToJsonElement
import kotlinx.serialization.json.jsonObject
import org.junit.Test

class ObservationRefreshProtocolEnvelopeTest {
    @Test(expected = IllegalArgumentException::class)
    fun `refresh request cannot carry correlation id`() {
        val payload = payload()
        val envelope = ProtocolEnvelope(
            messageId = REQUEST_ID,
            type = ObservationRefreshProtocol.TYPE_REFRESH,
            sentAtMs = 1_000,
            deviceId = DEVICE_ID,
            correlationId = OTHER_ID,
            payload = DeviceProtocol.json.encodeToJsonElement(payload).jsonObject,
        )

        ObservationRefreshProtocol.decodeRequest(envelope)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `refresh decoder rejects another message type`() {
        val payload = payload()
        val envelope = ProtocolEnvelope(
            messageId = REQUEST_ID,
            type = DeviceProtocol.TYPE_ACTION_COMMAND,
            sentAtMs = 1_000,
            deviceId = DEVICE_ID,
            payload = DeviceProtocol.json.encodeToJsonElement(payload).jsonObject,
        )

        ObservationRefreshProtocol.decodeRequest(envelope)
    }

    private fun payload(): DeviceObservationRefreshPayload =
        DeviceObservationRefreshPayload(
            requestId = REQUEST_ID,
            timeoutMs = 5_000,
            expectedStateFingerprint = "a".repeat(64),
            expectedActivePackage = "com.example",
            reason = "envelope fixture",
        )

    private companion object {
        const val DEVICE_ID = "11111111-1111-1111-1111-111111111111"
        const val REQUEST_ID = "22222222-2222-2222-2222-222222222222"
        const val OTHER_ID = "33333333-3333-3333-3333-333333333333"
    }
}
