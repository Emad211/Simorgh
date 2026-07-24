package ai.simorgh.android.protocol

import ai.simorgh.android.accessibility.AccessibilitySnapshot
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.encodeToJsonElement
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ObservationRefreshProtocolTest {
    @Test
    fun `refresh request survives strict decode and identity validation`() {
        val payload = DeviceObservationRefreshPayload(
            requestId = REQUEST_ID,
            timeoutMs = 5_000,
            expectedStateFingerprint = "a".repeat(64),
            expectedActivePackage = "com.example",
            reason = "fixture",
        )
        val envelope = ProtocolEnvelope(
            messageId = REQUEST_ID,
            type = ObservationRefreshProtocol.TYPE_REFRESH,
            sentAtMs = 1_000,
            deviceId = DEVICE_ID,
            payload = DeviceProtocol.json.encodeToJsonElement(payload).jsonObject,
        )

        val decoded = ObservationRefreshProtocol.decodeRequest(envelope)
        val validated = ObservationRefreshProtocol.validateRequest(
            requestEnvelopeId = envelope.messageId,
            payload = decoded,
        )

        assertEquals(payload, validated)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `refresh request id must equal envelope message id`() {
        ObservationRefreshProtocol.validateRequest(
            requestEnvelopeId = REQUEST_ID,
            payload = DeviceObservationRefreshPayload(
                requestId = OTHER_REQUEST_ID,
                timeoutMs = 5_000,
            ),
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun `refresh timeout is bounded`() {
        ObservationRefreshProtocol.validateRequest(
            requestEnvelopeId = REQUEST_ID,
            payload = DeviceObservationRefreshPayload(
                requestId = REQUEST_ID,
                timeoutMs = 10_001,
            ),
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun `expected fingerprint must be canonical lowercase hex`() {
        ObservationRefreshProtocol.validateRequest(
            requestEnvelopeId = REQUEST_ID,
            payload = DeviceObservationRefreshPayload(
                requestId = REQUEST_ID,
                timeoutMs = 5_000,
                expectedStateFingerprint = "A".repeat(64),
            ),
        )
    }

    @Test
    fun `refresh acknowledgement is correlated to request identity`() {
        val envelope = ObservationRefreshProtocol.acknowledgement(
            deviceId = DEVICE_ID,
            requestEnvelopeId = REQUEST_ID,
            requestId = REQUEST_ID,
            status = ObservationRefreshAckStatus.ACCEPTED,
            detail = "capture accepted",
            nowMs = 2_000,
        )
        val payload = DeviceProtocol.json.decodeFromJsonElement<
            DeviceObservationRefreshAckPayload
            >(envelope.payload)

        assertEquals(ObservationRefreshProtocol.TYPE_REFRESH_ACK, envelope.type)
        assertEquals(REQUEST_ID, envelope.correlationId)
        assertEquals(REQUEST_ID, payload.requestId)
        assertEquals(ObservationRefreshAckStatus.ACCEPTED, payload.status)
        assertEquals(2_000, payload.receivedAtMs)
    }

    @Test
    fun `correlated observation preserves ordinary snapshot payload`() {
        val snapshot = snapshot(SNAPSHOT_ID)
        val envelope = ObservationRefreshProtocol.correlatedObservation(
            deviceId = DEVICE_ID,
            refreshEnvelopeId = REQUEST_ID,
            streamId = STREAM_ID,
            sequence = 7,
            stateFingerprint = "b".repeat(64),
            snapshot = snapshot,
            messageId = OBSERVATION_MESSAGE_ID,
            nowMs = 3_000,
        )
        val payload = DeviceProtocol.json.decodeFromJsonElement<DeviceObservationPayload>(
            envelope.payload,
        )

        assertEquals(DeviceProtocol.TYPE_OBSERVATION, envelope.type)
        assertEquals(REQUEST_ID, envelope.correlationId)
        assertEquals(OBSERVATION_MESSAGE_ID, envelope.messageId)
        assertEquals(STREAM_ID, payload.streamId)
        assertEquals(7, payload.sequence)
        assertEquals(snapshot, payload.snapshot)
        assertNull(snapshot.rootNodeId)
        assertTrue(snapshot.nodes.isEmpty())
    }

    private fun snapshot(snapshotId: String): AccessibilitySnapshot = AccessibilitySnapshot(
        snapshotId = snapshotId,
        capturedAtMs = 2_500,
        activePackage = "com.example",
        activeWindowId = null,
        rootNodeId = null,
        windows = emptyList(),
        nodes = emptyList(),
        truncated = false,
        truncationReasons = emptyList(),
        maxDepthObserved = 0,
    )

    private companion object {
        const val DEVICE_ID = "11111111-1111-1111-1111-111111111111"
        const val REQUEST_ID = "22222222-2222-2222-2222-222222222222"
        const val OTHER_REQUEST_ID = "33333333-3333-3333-3333-333333333333"
        const val STREAM_ID = "44444444-4444-4444-4444-444444444444"
        const val SNAPSHOT_ID = "55555555-5555-5555-5555-555555555555"
        const val OBSERVATION_MESSAGE_ID = "66666666-6666-6666-6666-666666666666"
    }
}
