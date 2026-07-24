package ai.simorgh.android.protocol

import ai.simorgh.android.accessibility.AccessibilitySnapshot
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.encodeToJsonElement
import kotlinx.serialization.json.jsonObject
import java.util.UUID

@Serializable
data class ProtocolEnvelope(
    @SerialName("protocol_version")
    val protocolVersion: String = ProtocolVersion.CURRENT,
    @SerialName("message_id")
    val messageId: String,
    val type: String,
    @SerialName("sent_at_ms")
    val sentAtMs: Long,
    @SerialName("device_id")
    val deviceId: String? = null,
    @SerialName("correlation_id")
    val correlationId: String? = null,
    val payload: JsonObject,
)

@Serializable
data class DeviceRegistrationPayload(
    @SerialName("app_version")
    val appVersion: String,
    @SerialName("sdk_int")
    val sdkInt: Int,
    @SerialName("android_release")
    val androidRelease: String,
    val manufacturer: String,
    val model: String,
    @SerialName("build_fingerprint")
    val buildFingerprint: String,
    @SerialName("support_tier")
    val supportTier: String,
    val capabilities: List<String>,
)

@Serializable
data class DeviceRegisteredPayload(
    @SerialName("session_id")
    val sessionId: String,
    @SerialName("server_time_ms")
    val serverTimeMs: Long,
    @SerialName("heartbeat_interval_seconds")
    val heartbeatIntervalSeconds: Int,
)

@Serializable
data class DeviceHeartbeatPayload(
    val sequence: Long,
    @SerialName("app_uptime_ms")
    val appUptimeMs: Long,
)

@Serializable
data class DeviceHeartbeatAckPayload(
    val sequence: Long,
    @SerialName("server_time_ms")
    val serverTimeMs: Long,
)

@Serializable
data class DeviceObservationPayload(
    @SerialName("state_fingerprint")
    val stateFingerprint: String,
    val snapshot: AccessibilitySnapshot,
)

@Serializable
enum class ObservationAckStatus {
    @SerialName("accepted")
    ACCEPTED,

    @SerialName("duplicate")
    DUPLICATE,

    @SerialName("stale")
    STALE,
}

@Serializable
data class DeviceObservationAckPayload(
    @SerialName("snapshot_id")
    val snapshotId: String,
    val status: ObservationAckStatus,
    @SerialName("received_at_ms")
    val receivedAtMs: Long,
)

@Serializable
data class DeviceErrorPayload(
    val code: String,
    val message: String,
)

object DeviceProtocol {
    const val TYPE_REGISTER: String = "device.register"
    const val TYPE_REGISTERED: String = "device.registered"
    const val TYPE_HEARTBEAT: String = "device.heartbeat"
    const val TYPE_HEARTBEAT_ACK: String = "device.heartbeat_ack"
    const val TYPE_OBSERVATION: String = "device.observation"
    const val TYPE_OBSERVATION_ACK: String = "device.observation_ack"
    const val TYPE_ERROR: String = "device.error"

    val json: Json = Json {
        encodeDefaults = true
        explicitNulls = false
        ignoreUnknownKeys = false
    }

    fun registration(
        deviceId: String,
        payload: DeviceRegistrationPayload,
        nowMs: Long = System.currentTimeMillis(),
    ): ProtocolEnvelope = ProtocolEnvelope(
        messageId = UUID.randomUUID().toString(),
        type = TYPE_REGISTER,
        sentAtMs = nowMs,
        deviceId = deviceId,
        payload = json.encodeToJsonElement(payload).jsonObject,
    )

    fun heartbeat(
        deviceId: String,
        sequence: Long,
        appUptimeMs: Long,
        nowMs: Long = System.currentTimeMillis(),
    ): ProtocolEnvelope = ProtocolEnvelope(
        messageId = UUID.randomUUID().toString(),
        type = TYPE_HEARTBEAT,
        sentAtMs = nowMs,
        deviceId = deviceId,
        payload = json.encodeToJsonElement(
            DeviceHeartbeatPayload(sequence = sequence, appUptimeMs = appUptimeMs),
        ).jsonObject,
    )

    fun observation(
        deviceId: String,
        stateFingerprint: String,
        snapshot: AccessibilitySnapshot,
        nowMs: Long = System.currentTimeMillis(),
    ): ProtocolEnvelope = ProtocolEnvelope(
        messageId = UUID.randomUUID().toString(),
        type = TYPE_OBSERVATION,
        sentAtMs = nowMs,
        deviceId = deviceId,
        payload = json.encodeToJsonElement(
            DeviceObservationPayload(
                stateFingerprint = stateFingerprint,
                snapshot = snapshot,
            ),
        ).jsonObject,
    )

    fun encode(envelope: ProtocolEnvelope): String = json.encodeToString(envelope)

    fun decode(raw: String): ProtocolEnvelope = json.decodeFromString(raw)

    fun decodeRegistered(envelope: ProtocolEnvelope): DeviceRegisteredPayload =
        json.decodeFromJsonElement(envelope.payload)

    fun decodeHeartbeatAck(envelope: ProtocolEnvelope): DeviceHeartbeatAckPayload =
        json.decodeFromJsonElement(envelope.payload)

    fun decodeObservationAck(envelope: ProtocolEnvelope): DeviceObservationAckPayload =
        json.decodeFromJsonElement(envelope.payload)

    fun decodeError(envelope: ProtocolEnvelope): DeviceErrorPayload =
        json.decodeFromJsonElement(envelope.payload)
}
