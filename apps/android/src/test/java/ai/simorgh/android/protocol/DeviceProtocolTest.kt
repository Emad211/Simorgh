package ai.simorgh.android.protocol

import ai.simorgh.android.accessibility.AccessibilityNodeSnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.ScreenBounds
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

    @Test
    fun `observation preserves Persian semantic data and snapshot identity`() {
        val snapshot = AccessibilitySnapshot(
            snapshotId = "22222222-2222-2222-2222-222222222222",
            capturedAtMs = 9_000,
            activePackage = "com.example",
            activeWindowId = 1,
            rootNodeId = "root",
            windows = emptyList(),
            nodes = listOf(
                AccessibilityNodeSnapshot(
                    nodeId = "root",
                    path = "0",
                    depth = 0,
                    windowId = 1,
                    packageName = "com.example",
                    className = "android.widget.TextView",
                    text = "سلام سیمرغ",
                    bounds = ScreenBounds(0, 0, 200, 100),
                    semanticFingerprint = "semantic-root",
                    childCount = 0,
                    inputType = 0,
                    clickable = false,
                    longClickable = false,
                    focusable = false,
                    focused = false,
                    editable = false,
                    scrollable = false,
                    enabled = true,
                    selected = false,
                    checkable = false,
                    checked = false,
                    visibleToUser = true,
                    accessibilityFocused = false,
                    password = false,
                    heading = false,
                    actions = emptyList(),
                ),
            ),
            truncated = false,
            truncationReasons = emptyList(),
            maxDepthObserved = 0,
        )
        val envelope = DeviceProtocol.observation(
            deviceId = "11111111-1111-1111-1111-111111111111",
            stateFingerprint = "state-fingerprint",
            snapshot = snapshot,
            nowMs = 10_000,
        )

        val decodedEnvelope = DeviceProtocol.decode(DeviceProtocol.encode(envelope))
        val decodedPayload = DeviceProtocol.json.decodeFromJsonElement<DeviceObservationPayload>(
            decodedEnvelope.payload,
        )

        assertEquals(DeviceProtocol.TYPE_OBSERVATION, decodedEnvelope.type)
        assertEquals("state-fingerprint", decodedPayload.stateFingerprint)
        assertEquals(snapshot.snapshotId, decodedPayload.snapshot.snapshotId)
        assertEquals("سلام سیمرغ", decodedPayload.snapshot.nodes.single().text)
    }
}
