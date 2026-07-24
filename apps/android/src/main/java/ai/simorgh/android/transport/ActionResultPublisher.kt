package ai.simorgh.android.transport

import ai.simorgh.android.actions.AndroidActionContractValidator
import ai.simorgh.android.actions.PendingActionResultDelivery
import ai.simorgh.android.protocol.ActionResultAckStatus
import ai.simorgh.android.protocol.DeviceActionResultAckPayload
import ai.simorgh.android.protocol.DeviceProtocol
import ai.simorgh.android.protocol.ProtocolEnvelope
import java.io.Closeable

class ActionResultPublisher(
    private val deviceId: String,
    private val sender: (ProtocolEnvelope) -> Boolean,
    private val listener: (String) -> Unit = {},
    private val scheduler: ObservationScheduler = ExecutorObservationScheduler(),
    private val acknowledgementTimeoutMillis: Long = 10_000,
    private val maximumAttemptsPerConnection: Int = 3,
) : Closeable {
    private val lock = Any()

    private var connected = false
    private var closed = false
    private var delivery: ResultDelivery? = null
    private var retryTask: ScheduledObservationTask? = null

    init {
        require(acknowledgementTimeoutMillis > 0)
        require(maximumAttemptsPerConnection > 0)
    }

    fun submit(pending: PendingActionResultDelivery): Boolean {
        val validated = AndroidActionContractValidator.validate(pending.result)
        val envelope = DeviceProtocol.actionResult(
            deviceId = deviceId,
            commandEnvelopeId = pending.commandEnvelopeId,
            result = validated,
            messageId = pending.resultMessageId,
        )
        if (DeviceProtocol.encodedSizeBytes(envelope) > DeviceProtocol.MAX_DEVICE_MESSAGE_BYTES) {
            listener("action result ${pending.result.actionId} exceeds the transport byte limit")
            return false
        }

        synchronized(lock) {
            if (closed) {
                return false
            }
            val existing = delivery
            if (existing != null) {
                if (existing.envelope == envelope) {
                    scheduleSendLocked(delayMillis = 0)
                    return true
                }
                listener("another action result is already pending")
                return false
            }
            delivery = ResultDelivery(envelope = envelope)
            scheduleSendLocked(delayMillis = 0)
        }
        return true
    }

    fun setConnected(isConnected: Boolean) {
        synchronized(lock) {
            if (closed || connected == isConnected) {
                return
            }
            connected = isConnected
            retryTask?.cancel()
            retryTask = null
            delivery = delivery?.copy(
                attemptsOnConnection = 0,
                awaitingAcknowledgement = false,
            )
            if (connected) {
                scheduleSendLocked(delayMillis = 0)
            }
        }
    }

    fun acknowledge(
        acknowledgement: DeviceActionResultAckPayload,
        correlationId: String?,
    ): Boolean {
        synchronized(lock) {
            val active = delivery ?: return false
            val result = active.result
            if (
                correlationId != active.envelope.messageId ||
                acknowledgement.commandId != result.commandId ||
                acknowledgement.actionId != result.actionId
            ) {
                return false
            }

            retryTask?.cancel()
            retryTask = null
            delivery = null
            when (acknowledgement.status) {
                ActionResultAckStatus.ACCEPTED,
                ActionResultAckStatus.DUPLICATE,
                -> listener("action result ${result.actionId} acknowledged")

                ActionResultAckStatus.UNKNOWN_ACTION,
                ActionResultAckStatus.REJECTED,
                -> listener(
                    "action result ${result.actionId} was not accepted: " +
                        acknowledgement.status.name.lowercase(),
                )
            }
            return true
        }
    }

    fun pendingActionId(): String? = synchronized(lock) { delivery?.result?.actionId }

    override fun close() {
        synchronized(lock) {
            if (closed) {
                return
            }
            closed = true
            connected = false
            retryTask?.cancel()
            retryTask = null
            delivery = null
        }
        scheduler.close()
    }

    private fun scheduleSendLocked(delayMillis: Long) {
        if (
            closed ||
            !connected ||
            retryTask != null ||
            delivery?.awaitingAcknowledgement == true ||
            delivery == null
        ) {
            return
        }
        retryTask = scheduler.schedule(delayMillis) {
            synchronized(lock) {
                retryTask = null
            }
            attemptSend()
        }
    }

    private fun attemptSend() {
        val outgoing: ResultDelivery
        synchronized(lock) {
            val active = delivery ?: return
            if (closed || !connected || active.awaitingAcknowledgement) {
                return
            }
            if (active.attemptsOnConnection >= maximumAttemptsPerConnection) {
                listener(
                    "action result ${active.result.actionId} paused after " +
                        "$maximumAttemptsPerConnection attempts",
                )
                return
            }
            outgoing = active.copy(
                attemptsOnConnection = active.attemptsOnConnection + 1,
                awaitingAcknowledgement = true,
            )
            delivery = outgoing
        }

        val sent = sender(outgoing.envelope)
        synchronized(lock) {
            val current = delivery
            if (closed || current?.envelope?.messageId != outgoing.envelope.messageId) {
                return
            }
            if (!sent) {
                connected = false
                delivery = outgoing.copy(
                    attemptsOnConnection = (outgoing.attemptsOnConnection - 1).coerceAtLeast(0),
                    awaitingAcknowledgement = false,
                )
                listener("action result ${outgoing.result.actionId} paused until reconnect")
                return
            }
            retryTask = scheduler.schedule(acknowledgementTimeoutMillis) {
                onAcknowledgementTimeout(outgoing.envelope.messageId)
            }
        }
    }

    private fun onAcknowledgementTimeout(messageId: String) {
        synchronized(lock) {
            retryTask = null
            val active = delivery ?: return
            if (active.envelope.messageId != messageId || !active.awaitingAcknowledgement) {
                return
            }
            delivery = active.copy(awaitingAcknowledgement = false)
            listener("action result ${active.result.actionId} acknowledgement timeout")
            scheduleSendLocked(delayMillis = 0)
        }
    }

    private data class ResultDelivery(
        val envelope: ProtocolEnvelope,
        val attemptsOnConnection: Int = 0,
        val awaitingAcknowledgement: Boolean = false,
    ) {
        val result
            get() = DeviceProtocol.json.decodeFromJsonElement<ai.simorgh.android.actions.AndroidActionResult>(
                envelope.payload,
            )
    }
}
