package ai.simorgh.android.protocol

import kotlinx.serialization.json.decodeFromJsonElement
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class DeviceProtocolTest {
    @Test
    fun `registration survives an exact JSON round trip`() {
        val payload = DeviceRegistrationPayload(
            appVersion = "0.1.0",
            sdkInt = 31,
            androidRelease = "12",
            manufacturer = "Samsung",
            model = "SM-A536B",
            buildFingerprint = "samsung/a53/test",
            supportTier = "FULL",
            capabilities = listOf("device.identity", "android.accessibility.gesture.platform"),
        )
        val envelope = DeviceProtocol.registration(
            deviceId = "11111111-1111-1111-1111-111111111111",
            payload = payload,
            nowMs = 123_456,
        )

        val decoded = DeviceProtocol.decode(DeviceProtocol.encode(envelope))
        val decodedPayload = DeviceProtocol.json.decodeFromJsonElement<DeviceRegistrationPayload>(
            decoded.payload,
        )

        assertEquals(ProtocolVersion.CURRENT, decoded.protocolVersion)
        assertEquals(DeviceProtocol.TYPE_REGISTER, decoded.type)
        assertEquals(envelope.deviceId, decoded.deviceId)
        assertNull(decoded.correlationId)
        assertEquals(123_456, decoded.sentAtMs)
        assertEquals(payload, decodedPayload)
    }

    @Test
    fun `heartbeat contains the expected sequence and uptime`() {
        val envelope = DeviceProtocol.heartbeat(
            deviceId = "11111111-1111-1111-1111-111111111111",
            sequence = 9,
            appUptimeMs = 44_000,
            nowMs = 123_456,
        )
        val heartbeat = DeviceProtocol.json.decodeFromJsonElement<DeviceHeartbeatPayload>(
            envelope.payload,
        )

        assertEquals(DeviceProtocol.TYPE_HEARTBEAT, envelope.type)
        assertEquals(9, heartbeat.sequence)
        assertEquals(44_000, heartbeat.appUptimeMs)
    }
}
