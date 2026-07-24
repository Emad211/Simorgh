package ai.simorgh.android.protocol

import ai.simorgh.android.accessibility.AccessibilitySnapshot
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.encodeToJsonElement
import kotlinx.serialization.json.jsonObject
import java.util.UUID

@Serializable
data class DeviceObservationRefreshPayload(
    @SerialName("request_id")
    val requestId: String,
    @SerialName("timeout_ms")
    val timeoutMs: Long,
    @SerialName("expected_state_fingerprint")
    val expectedStateFingerprint: String? = null,
    @SerialName("expected_active_package")
    val expectedActivePackage: String? = null,
    val reason: String = "operator requested fresh observation",
)

@Serializable
enum class ObservationRefreshAckStatus {
    @SerialName("accepted")
    ACCEPTED,

    @SerialName("duplicate")
    DUPLICATE,

    @SerialName("busy")
    BUSY,

    @SerialName("expired")
    EXPIRED,

    @SerialName("observer_unavailable")
    OBSERVER_UNAVAILABLE,

    @SerialName("rejected")
    REJECTED,
}

@Serializable
data class DeviceObservationRefreshAckPayload(
    @SerialName("request_id")
    val requestId: String,
    val status: ObservationRefreshAckStatus,
    @SerialName("received_at_ms")
    val receivedAtMs: Long,
    val detail: String = "",
)

object ObservationRefreshProtocol {
    const val TYPE_REFRESH: String = "device.observation_refresh"
    const val TYPE_REFRESH_ACK: String = "device.observation_refresh_ack"
    const val CAPABILITY: String = "android.observation.refresh.v1"

    fun decodeRequest(envelope: ProtocolEnvelope): DeviceObservationRefreshPayload {
        require(envelope.type == TYPE_REFRESH) { "unexpected refresh message type" }
        require(envelope.correlationId == null) {
            "refresh request cannot declare correlation_id"
        }
        val payload = DeviceProtocol.json.decodeFromJsonElement(
            DeviceObservationRefreshPayload.serializer(),
            envelope.payload,
        )
        return validateRequest(
            requestEnvelopeId = envelope.messageId,
            payload = payload,
        )
    }

    fun acknowledgement(
        deviceId: String,
        requestEnvelopeId: String,
        requestId: String,
        status: ObservationRefreshAckStatus,
        detail: String = "",
        nowMs: Long = System.currentTimeMillis(),
    ): ProtocolEnvelope {
        validateRequestIdentity(requestEnvelopeId, requestId)
        return ProtocolEnvelope(
            messageId = UUID.randomUUID().toString(),
            type = TYPE_REFRESH_ACK,
            sentAtMs = nowMs,
            deviceId = deviceId,
            correlationId = requestEnvelopeId,
            payload = DeviceProtocol.json.encodeToJsonElement(
                DeviceObservationRefreshAckPayload(
                    requestId = requestId,
                    status = status,
                    receivedAtMs = nowMs,
                    detail = detail.take(1_000),
                ),
            ).jsonObject,
        )
    }

    fun correlatedObservation(
        deviceId: String,
        refreshEnvelopeId: String,
        streamId: String,
        sequence: Long,
        stateFingerprint: String,
        snapshot: AccessibilitySnapshot,
        messageId: String = UUID.randomUUID().toString(),
        nowMs: Long = System.currentTimeMillis(),
    ): ProtocolEnvelope {
        requireUuid(refreshEnvelopeId, "refresh envelope id")
        return ProtocolEnvelope(
            messageId = messageId,
            type = DeviceProtocol.TYPE_OBSERVATION,
            sentAtMs = nowMs,
            deviceId = deviceId,
            correlationId = refreshEnvelopeId,
            payload = DeviceProtocol.json.encodeToJsonElement(
                DeviceObservationPayload(
                    streamId = streamId,
                    sequence = sequence,
                    stateFingerprint = stateFingerprint,
                    snapshot = snapshot,
                ),
            ).jsonObject,
        )
    }

    fun validateRequest(
        requestEnvelopeId: String,
        payload: DeviceObservationRefreshPayload,
    ): DeviceObservationRefreshPayload {
        validateRequestIdentity(requestEnvelopeId, payload.requestId)
        require(payload.timeoutMs in 250..10_000) {
            "refresh timeout_ms must be in 250..10000"
        }
        payload.expectedStateFingerprint?.let { fingerprint ->
            require(fingerprint.length == 64 && fingerprint.all(::isLowercaseHex)) {
                "expected_state_fingerprint must be 64 lowercase hex characters"
            }
        }
        payload.expectedActivePackage?.let { packageName ->
            require(packageName.isNotBlank() && packageName.length <= 512) {
                "expected_active_package is invalid"
            }
        }
        require(payload.reason.length <= 1_000) { "refresh reason exceeds 1000 characters" }
        return payload
    }

    private fun validateRequestIdentity(requestEnvelopeId: String, requestId: String) {
        requireUuid(requestEnvelopeId, "refresh envelope message_id")
        require(requestId == requestEnvelopeId) {
            "refresh request_id must equal envelope message_id"
        }
    }

    private fun requireUuid(value: String, field: String) {
        require(runCatching { UUID.fromString(value) }.isSuccess) { "$field must be a UUID" }
    }

    private fun isLowercaseHex(character: Char): Boolean =
        character in '0'..'9' || character in 'a'..'f'
}
