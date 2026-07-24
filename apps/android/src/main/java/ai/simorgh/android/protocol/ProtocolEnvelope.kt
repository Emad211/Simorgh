package ai.simorgh.android.protocol

import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.actions.AndroidActionCommand
import ai.simorgh.android.actions.AndroidActionResult
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
    @SerialName("stream_id")
    val streamId: String,
    val sequence: Long,
    @SerialName("state_fingerprint")
    val stateFingerprint: String,
    val snapshot: AccessibilitySnapshot,
)

@Serializable
enum class ObservationAckStatus {
    @SerialName("accepted")
    ACCEPTED,

    @SerialName("unchanged")
    UNCHANGED,

    @SerialName("duplicate")
    DUPLICATE,

    @SerialName("stale")
    STALE,
}

@Serializable
data class DeviceObservationAckPayload(
    @SerialName("stream_id")
    val streamId: String,
    val sequence: Long,
    @SerialName("snapshot_id")
    val snapshotId: String,
    val status: ObservationAckStatus,
    @SerialName("received_at_ms")
    val receivedAtMs: Long,
)

@Serializable
enum class ActionCommandAckStatus {
    @SerialName("accepted")
    ACCEPTED,

    @SerialName("duplicate")
    DUPLICATE,

    @SerialName("busy")
    BUSY,

    @SerialName("expired")
    EXPIRED,

    @SerialName("rejected")
    REJECTED,
}

@Serializable
data class DeviceActionCommandAckPayload(
    @SerialName("command_id")
    val commandId: String,
    @SerialName("action_id")
    val actionId: String,
    val status: ActionCommandAckStatus,
    @SerialName("received_at_ms")
    val receivedAtMs: Long,
    val detail: String = "",
)

@Serializable
enum class ActionResultAckStatus {
    @SerialName("accepted")
    ACCEPTED,

    @SerialName("duplicate")
    DUPLICATE,

    @SerialName("unknown_action")
    UNKNOWN_ACTION,

    @SerialName("rejected")
    REJECTED,
}

@Serializable
data class DeviceActionResultAckPayload(
    @SerialName("command_id")
    val commandId: String,
    @SerialName("action_id")
    val actionId: String,
    val status: ActionResultAckStatus,
    @SerialName("received_at_ms")
    val receivedAtMs: Long,
    val detail: String = "",
)

@Serializable
data class DeviceActionCancelPayload(
    @SerialName("command_id")
    val commandId: String,
    @SerialName("action_id")
    val actionId: String,
    val reason: String = "",
)

@Serializable
enum class ActionCancelAckStatus {
    @SerialName("accepted")
    ACCEPTED,

    @SerialName("duplicate")
    DUPLICATE,

    @SerialName("not_found")
    NOT_FOUND,

    @SerialName("completed")
    COMPLETED,
}

@Serializable
data class DeviceActionCancelAckPayload(
    @SerialName("command_id")
    val commandId: String,
    @SerialName("action_id")
    val actionId: String,
    val status: ActionCancelAckStatus,
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
    const val TYPE_ACTION_COMMAND: String = "device.action_command"
    const val TYPE_ACTION_COMMAND_ACK: String = "device.action_command_ack"
    const val TYPE_ACTION_RESULT: String = "device.action_result"
    const val TYPE_ACTION_RESULT_ACK: String = "device.action_result_ack"
    const val TYPE_ACTION_CANCEL: String = "device.action_cancel"
    const val TYPE_ACTION_CANCEL_ACK: String = "device.action_cancel_ack"
    const val TYPE_ERROR: String = "device.error"
    const val MAX_DEVICE_MESSAGE_BYTES: Int = 2_000_000

    val json: Json = Json {
        encodeDefaults = true
        explicitNulls = false
        ignoreUnknownKeys = false
        classDiscriminator = "kind"
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
        streamId: String,
        sequence: Long,
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
                streamId = streamId,
                sequence = sequence,
                stateFingerprint = stateFingerprint,
                snapshot = snapshot,
            ),
        ).jsonObject,
    )

    fun actionCommandAck(
        deviceId: String,
        commandEnvelopeId: String,
        command: AndroidActionCommand,
        status: ActionCommandAckStatus,
        detail: String = "",
        nowMs: Long = System.currentTimeMillis(),
    ): ProtocolEnvelope = ProtocolEnvelope(
        messageId = UUID.randomUUID().toString(),
        type = TYPE_ACTION_COMMAND_ACK,
        sentAtMs = nowMs,
        deviceId = deviceId,
        correlationId = commandEnvelopeId,
        payload = json.encodeToJsonElement(
            DeviceActionCommandAckPayload(
                commandId = command.commandId,
                actionId = command.actionId,
                status = status,
                receivedAtMs = nowMs,
                detail = detail.take(1_000),
            ),
        ).jsonObject,
    )

    fun actionResult(
        deviceId: String,
        commandEnvelopeId: String,
        result: AndroidActionResult,
        messageId: String = UUID.randomUUID().toString(),
        nowMs: Long = System.currentTimeMillis(),
    ): ProtocolEnvelope = ProtocolEnvelope(
        messageId = messageId,
        type = TYPE_ACTION_RESULT,
        sentAtMs = nowMs,
        deviceId = deviceId,
        correlationId = commandEnvelopeId,
        payload = json.encodeToJsonElement(result).jsonObject,
    )

    fun actionCancelAck(
        deviceId: String,
        cancelEnvelopeId: String,
        cancellation: DeviceActionCancelPayload,
        status: ActionCancelAckStatus,
        nowMs: Long = System.currentTimeMillis(),
    ): ProtocolEnvelope = ProtocolEnvelope(
        messageId = UUID.randomUUID().toString(),
        type = TYPE_ACTION_CANCEL_ACK,
        sentAtMs = nowMs,
        deviceId = deviceId,
        correlationId = cancelEnvelopeId,
        payload = json.encodeToJsonElement(
            DeviceActionCancelAckPayload(
                commandId = cancellation.commandId,
                actionId = cancellation.actionId,
                status = status,
                receivedAtMs = nowMs,
            ),
        ).jsonObject,
    )

    fun encode(envelope: ProtocolEnvelope): String = json.encodeToString(envelope)

    fun encodedSizeBytes(envelope: ProtocolEnvelope): Int =
        encode(envelope).toByteArray(Charsets.UTF_8).size

    fun decode(raw: String): ProtocolEnvelope = json.decodeFromString(raw)

    fun decodeRegistered(envelope: ProtocolEnvelope): DeviceRegisteredPayload =
        json.decodeFromJsonElement(envelope.payload)

    fun decodeHeartbeatAck(envelope: ProtocolEnvelope): DeviceHeartbeatAckPayload =
        json.decodeFromJsonElement(envelope.payload)

    fun decodeObservationAck(envelope: ProtocolEnvelope): DeviceObservationAckPayload =
        json.decodeFromJsonElement(envelope.payload)

    fun decodeActionCommand(envelope: ProtocolEnvelope): AndroidActionCommand =
        json.decodeFromJsonElement(envelope.payload)

    fun decodeActionResultAck(envelope: ProtocolEnvelope): DeviceActionResultAckPayload =
        json.decodeFromJsonElement(envelope.payload)

    fun decodeActionCancel(envelope: ProtocolEnvelope): DeviceActionCancelPayload =
        json.decodeFromJsonElement(envelope.payload)

    fun decodeError(envelope: ProtocolEnvelope): DeviceErrorPayload =
        json.decodeFromJsonElement(envelope.payload)
}
