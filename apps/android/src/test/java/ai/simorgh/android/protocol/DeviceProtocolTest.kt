package ai.simorgh.android.protocol

import ai.simorgh.android.accessibility.AccessibilityNodeSnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
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
            deviceId = DEVICE_ID,
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
            deviceId = DEVICE_ID,
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
    fun `observation preserves stream ordering Persian data and canonical fingerprint`() {
        val snapshot = snapshot(text = "سلام سیمرغ")
        val stateFingerprint = AccessibilitySnapshotFingerprint.calculate(snapshot)
        val envelope = DeviceProtocol.observation(
            deviceId = DEVICE_ID,
            streamId = STREAM_ID,
            sequence = 7,
            stateFingerprint = stateFingerprint,
            snapshot = snapshot,
            nowMs = 10_000,
        )

        val decodedEnvelope = DeviceProtocol.decode(DeviceProtocol.encode(envelope))
        val decodedPayload = DeviceProtocol.json.decodeFromJsonElement<DeviceObservationPayload>(
            decodedEnvelope.payload,
        )

        assertEquals(DeviceProtocol.TYPE_OBSERVATION, decodedEnvelope.type)
        assertEquals(STREAM_ID, decodedPayload.streamId)
        assertEquals(7, decodedPayload.sequence)
        assertEquals(stateFingerprint, decodedPayload.stateFingerprint)
        assertEquals(snapshot.snapshotId, decodedPayload.snapshot.snapshotId)
        assertEquals("سلام سیمرغ", decodedPayload.snapshot.nodes.single().text)
    }

    @Test
    fun `canonical state fingerprint matches the Core golden vector`() {
        val snapshot = snapshot(text = "گزینه")

        assertEquals(
            "dc012d2ab21c3ad4308036eeddbe2522be4ab900f2b54eb24771341d2c79a056",
            AccessibilitySnapshotFingerprint.calculate(snapshot),
        )
    }

    private fun snapshot(text: String): AccessibilitySnapshot = AccessibilitySnapshot(
        snapshotId = SNAPSHOT_ID,
        capturedAtMs = 9_000,
        activePackage = "com.example",
        activeWindowId = 1,
        rootNodeId = ROOT_ID,
        windows = emptyList(),
        nodes = listOf(
            AccessibilityNodeSnapshot(
                nodeId = ROOT_ID,
                path = "0",
                depth = 0,
                windowId = 1,
                packageName = "com.example",
                className = "android.widget.CheckBox",
                text = text,
                bounds = ScreenBounds(0, 0, 100, 100),
                semanticFingerprint = SEMANTIC_ID,
                childCount = 0,
                inputType = 0,
                clickable = true,
                longClickable = false,
                focusable = true,
                focused = false,
                editable = false,
                scrollable = false,
                enabled = true,
                selected = false,
                checkable = true,
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

    private companion object {
        const val DEVICE_ID = "11111111-1111-1111-1111-111111111111"
        const val STREAM_ID = "33333333-3333-3333-3333-333333333333"
        const val SNAPSHOT_ID = "22222222-2222-2222-2222-222222222222"
        const val ROOT_ID = "111111111111111111111111"
        const val SEMANTIC_ID = "222222222222222222222222"
    }
}
