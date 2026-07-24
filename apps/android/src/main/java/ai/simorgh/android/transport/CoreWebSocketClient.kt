package ai.simorgh.android.transport

import android.os.SystemClock
import ai.simorgh.android.actions.AndroidActionCommand
import ai.simorgh.android.device.DeviceCapabilities
import ai.simorgh.android.protocol.DeviceActionCancelPayload
import ai.simorgh.android.protocol.DeviceActionResultAckPayload
import ai.simorgh.android.protocol.DeviceObservationAckPayload
import ai.simorgh.android.protocol.DeviceProtocol
import ai.simorgh.android.protocol.DeviceRegistrationPayload
import ai.simorgh.android.protocol.ProtocolEnvelope
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.io.Closeable
import java.util.ArrayDeque
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

interface CoreConnectionListener {
    fun onStateChanged(state: ConnectionState)

    fun onProtocolEvent(detail: String)

    fun onObservationAcknowledged(
        acknowledgement: DeviceObservationAckPayload,
        correlationId: String?,
    ) = Unit

    fun onActionCommand(
        commandEnvelopeId: String,
        command: AndroidActionCommand,
    ) = Unit

    fun onActionCancellation(
        cancelEnvelopeId: String,
        cancellation: DeviceActionCancelPayload,
    ) = Unit

    fun onActionResultAcknowledged(
        acknowledgement: DeviceActionResultAckPayload,
        correlationId: String?,
    ) = Unit
}

class CoreWebSocketClient(
    private val deviceId: String,
    private val capabilities: DeviceCapabilities,
    private val listener: CoreConnectionListener,
    private val reconnectPolicy: ReconnectPolicy = ReconnectPolicy(),
    private val scheduler: ScheduledExecutorService = Executors.newSingleThreadScheduledExecutor(),
    private val httpClient: OkHttpClient = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .build(),
) : Closeable {
    private val lock = Any()
    private val outboundQueue = ArrayDeque<String>()

    private var generation: Long = 0
    private var activeConfig: CoreConnectionConfig? = null
    private var socket: WebSocket? = null
    private var reconnectFuture: ScheduledFuture<*>? = null
    private var heartbeatFuture: ScheduledFuture<*>? = null
    private var reconnectAttempt: Int = 0
    private var heartbeatSequence: Long = 0
    private var registered: Boolean = false
    private var stopped: Boolean = true

    fun connect(config: CoreConnectionConfig) {
        val validated = config.validated()
        val currentGeneration: Long
        synchronized(lock) {
            generation += 1
            currentGeneration = generation
            stopped = false
            registered = false
            reconnectAttempt = 0
            heartbeatSequence = 0
            activeConfig = validated
            cancelScheduledTasksLocked()
            socket?.cancel()
            socket = null
        }
        openSocket(currentGeneration)
    }

    fun disconnect() {
        val socketToClose: WebSocket?
        synchronized(lock) {
            generation += 1
            stopped = true
            registered = false
            activeConfig = null
            cancelScheduledTasksLocked()
            socketToClose = socket
            socket = null
            outboundQueue.clear()
        }
        socketToClose?.close(NORMAL_CLOSURE_CODE, "user disconnect")
        emitState(ConnectionState.Disconnected)
    }

    fun send(envelope: ProtocolEnvelope): Boolean {
        val encoded = DeviceProtocol.encode(envelope)
        if (encoded.toByteArray(Charsets.UTF_8).size > DeviceProtocol.MAX_DEVICE_MESSAGE_BYTES) {
            return false
        }

        synchronized(lock) {
            val activeSocket = socket
            val immediateOnly = envelope.type == DeviceProtocol.TYPE_OBSERVATION ||
                envelope.type == DeviceProtocol.TYPE_ACTION_RESULT
            if (immediateOnly) {
                if (!registered || stopped || activeSocket == null) {
                    return false
                }
                val sent = activeSocket.send(encoded)
                if (!sent) {
                    activeSocket.cancel()
                }
                return sent
            }

            if (registered && activeSocket != null) {
                if (activeSocket.send(encoded)) {
                    return true
                }
                activeSocket.cancel()
            }
            if (outboundQueue.size >= MAX_OUTBOUND_QUEUE_SIZE) {
                outboundQueue.removeFirst()
            }
            outboundQueue.addLast(encoded)
            return true
        }
    }

    override fun close() {
        disconnect()
        scheduler.shutdownNow()
        httpClient.dispatcher.executorService.shutdown()
        httpClient.connectionPool.evictAll()
    }

    private fun openSocket(expectedGeneration: Long) {
        val config = synchronized(lock) {
            if (stopped || generation != expectedGeneration) {
                return
            }
            activeConfig
        } ?: return

        emitState(ConnectionState(ConnectionPhase.CONNECTING))
        val request = Request.Builder()
            .url(config.endpoint)
            .header("Authorization", "Bearer ${config.deviceToken}")
            .build()
        val openedSocket = httpClient.newWebSocket(
            request,
            SocketListener(expectedGeneration),
        )
        synchronized(lock) {
            if (generation == expectedGeneration && !stopped) {
                socket = openedSocket
            } else {
                openedSocket.cancel()
            }
        }
    }

    private fun sendRegistration(webSocket: WebSocket, expectedGeneration: Long) {
        val registration = DeviceProtocol.registration(
            deviceId = deviceId,
            payload = DeviceRegistrationPayload(
                appVersion = capabilities.appVersion,
                sdkInt = capabilities.sdkInt,
                androidRelease = capabilities.androidRelease,
                manufacturer = capabilities.manufacturer,
                model = capabilities.model,
                buildFingerprint = capabilities.buildFingerprint,
                supportTier = capabilities.supportTier.name,
                capabilities = capabilities.capabilities.sorted(),
            ),
        )
        if (!isCurrent(expectedGeneration) || !webSocket.send(DeviceProtocol.encode(registration))) {
            webSocket.cancel()
        }
    }

    private fun handleMessage(
        webSocket: WebSocket,
        expectedGeneration: Long,
        rawMessage: String,
    ) {
        if (!isCurrent(expectedGeneration)) {
            return
        }
        if (rawMessage.toByteArray(Charsets.UTF_8).size > DeviceProtocol.MAX_DEVICE_MESSAGE_BYTES) {
            listener.onProtocolEvent("پیام هسته از سقف مجاز بزرگ‌تر بود")
            webSocket.close(MESSAGE_TOO_BIG_CLOSURE_CODE, "core message too large")
            return
        }

        val envelope = runCatching { DeviceProtocol.decode(rawMessage) }
            .getOrElse { error ->
                listener.onProtocolEvent("پیام نامعتبر از هسته: ${error.message.orEmpty()}")
                webSocket.cancel()
                return
            }

        if (!isUuid(envelope.messageId)) {
            listener.onProtocolEvent("شناسه پیام هسته UUID معتبر نیست")
            webSocket.cancel()
            return
        }
        if (envelope.sentAtMs < 0) {
            listener.onProtocolEvent("زمان پیام هسته نامعتبر است")
            webSocket.cancel()
            return
        }
        if (envelope.protocolVersion != capabilities.protocolVersion) {
            listener.onProtocolEvent("نسخه پروتکل هسته با گوشی سازگار نیست")
            webSocket.cancel()
            return
        }
        if (envelope.deviceId != null && envelope.deviceId != deviceId) {
            listener.onProtocolEvent("شناسه دستگاه در پاسخ هسته نادرست است")
            webSocket.cancel()
            return
        }

        when (envelope.type) {
            DeviceProtocol.TYPE_REGISTERED -> handleRegistered(
                webSocket = webSocket,
                expectedGeneration = expectedGeneration,
                envelope = envelope,
            )

            DeviceProtocol.TYPE_HEARTBEAT_ACK -> {
                val acknowledgement = runCatching {
                    DeviceProtocol.decodeHeartbeatAck(envelope)
                }.getOrElse { return }
                listener.onProtocolEvent("heartbeat ${acknowledgement.sequence} تأیید شد")
            }

            DeviceProtocol.TYPE_OBSERVATION_ACK -> {
                val acknowledgement = runCatching {
                    DeviceProtocol.decodeObservationAck(envelope)
                }.getOrElse { error ->
                    listener.onProtocolEvent(
                        "پاسخ Observation نامعتبر است: ${error.message.orEmpty()}",
                    )
                    return
                }
                listener.onObservationAcknowledged(
                    acknowledgement = acknowledgement,
                    correlationId = envelope.correlationId,
                )
            }

            DeviceProtocol.TYPE_ACTION_COMMAND -> {
                val command = runCatching {
                    DeviceProtocol.decodeActionCommand(envelope)
                }.getOrElse { error ->
                    listener.onProtocolEvent(
                        "فرمان Android نامعتبر است: ${error.message.orEmpty()}",
                    )
                    webSocket.cancel()
                    return
                }
                invokeListenerOrCancel(webSocket, "action command") {
                    listener.onActionCommand(
                        commandEnvelopeId = envelope.messageId,
                        command = command,
                    )
                }
            }

            DeviceProtocol.TYPE_ACTION_CANCEL -> {
                val cancellation = runCatching {
                    DeviceProtocol.decodeActionCancel(envelope)
                }.getOrElse { error ->
                    listener.onProtocolEvent(
                        "لغو فرمان Android نامعتبر است: ${error.message.orEmpty()}",
                    )
                    webSocket.cancel()
                    return
                }
                invokeListenerOrCancel(webSocket, "action cancellation") {
                    listener.onActionCancellation(
                        cancelEnvelopeId = envelope.messageId,
                        cancellation = cancellation,
                    )
                }
            }

            DeviceProtocol.TYPE_ACTION_RESULT_ACK -> {
                val acknowledgement = runCatching {
                    DeviceProtocol.decodeActionResultAck(envelope)
                }.getOrElse { error ->
                    listener.onProtocolEvent(
                        "پاسخ نتیجه فرمان نامعتبر است: ${error.message.orEmpty()}",
                    )
                    return
                }
                listener.onActionResultAcknowledged(
                    acknowledgement = acknowledgement,
                    correlationId = envelope.correlationId,
                )
            }

            DeviceProtocol.TYPE_ERROR -> {
                val error = runCatching { DeviceProtocol.decodeError(envelope) }.getOrNull()
                listener.onProtocolEvent(
                    error?.let { "${it.code}: ${it.message}" } ?: "خطای ناشناخته از هسته",
                )
            }

            else -> {
                listener.onProtocolEvent("نوع پیام پشتیبانی‌نشده از هسته: ${envelope.type}")
                webSocket.cancel()
            }
        }
    }

    private fun handleRegistered(
        webSocket: WebSocket,
        expectedGeneration: Long,
        envelope: ProtocolEnvelope,
    ) {
        val registeredPayload = runCatching {
            DeviceProtocol.decodeRegistered(envelope)
        }.getOrElse { error ->
            listener.onProtocolEvent("پاسخ ثبت دستگاه نامعتبر است: ${error.message.orEmpty()}")
            webSocket.cancel()
            return
        }
        synchronized(lock) {
            if (generation != expectedGeneration || stopped) {
                return
            }
            registered = true
            reconnectAttempt = 0
        }
        scheduleHeartbeat(
            expectedGeneration = expectedGeneration,
            intervalSeconds = registeredPayload.heartbeatIntervalSeconds,
        )
        flushOutboundQueue(webSocket, expectedGeneration)
        emitState(ConnectionState(ConnectionPhase.CONNECTED))
        listener.onProtocolEvent("اتصال دستگاه با هسته تأیید شد")
    }

    private fun invokeListenerOrCancel(
        webSocket: WebSocket,
        eventName: String,
        callback: () -> Unit,
    ) {
        runCatching(callback).onFailure { error ->
            listener.onProtocolEvent(
                "$eventName processing failed: ${error.javaClass.simpleName}",
            )
            webSocket.cancel()
        }
    }

    private fun flushOutboundQueue(webSocket: WebSocket, expectedGeneration: Long) {
        while (true) {
            val next = synchronized(lock) {
                if (!registered || generation != expectedGeneration || stopped) {
                    return
                }
                outboundQueue.pollFirst()
            } ?: return
            if (!webSocket.send(next)) {
                synchronized(lock) {
                    outboundQueue.addFirst(next)
                }
                webSocket.cancel()
                return
            }
        }
    }

    private fun scheduleHeartbeat(expectedGeneration: Long, intervalSeconds: Int) {
        val safeInterval = intervalSeconds.coerceIn(MIN_HEARTBEAT_SECONDS, MAX_HEARTBEAT_SECONDS)
        synchronized(lock) {
            heartbeatFuture?.cancel(false)
            heartbeatFuture = scheduler.scheduleAtFixedRate(
                { sendHeartbeat(expectedGeneration) },
                safeInterval.toLong(),
                safeInterval.toLong(),
                TimeUnit.SECONDS,
            )
        }
    }

    private fun sendHeartbeat(expectedGeneration: Long) {
        val activeSocket: WebSocket
        val sequence: Long
        synchronized(lock) {
            if (stopped || generation != expectedGeneration || !registered) {
                return
            }
            activeSocket = socket ?: return
            heartbeatSequence += 1
            sequence = heartbeatSequence
        }
        val heartbeat = DeviceProtocol.heartbeat(
            deviceId = deviceId,
            sequence = sequence,
            appUptimeMs = SystemClock.elapsedRealtime(),
        )
        if (!activeSocket.send(DeviceProtocol.encode(heartbeat))) {
            activeSocket.cancel()
        }
    }

    private fun handleDisconnected(expectedGeneration: Long, detail: String?) {
        val attempt: Int
        val delayMillis: Long
        synchronized(lock) {
            if (generation != expectedGeneration || stopped) {
                return
            }
            if (reconnectFuture?.isDone == false) {
                return
            }
            registered = false
            socket = null
            heartbeatFuture?.cancel(false)
            heartbeatFuture = null
            reconnectAttempt += 1
            attempt = reconnectAttempt
            delayMillis = reconnectPolicy.delayMillis(attempt)
            reconnectFuture = scheduler.schedule(
                { openSocket(expectedGeneration) },
                delayMillis,
                TimeUnit.MILLISECONDS,
            )
        }
        emitState(
            ConnectionState(
                phase = ConnectionPhase.RETRY_WAIT,
                detail = detail,
                reconnectAttempt = attempt,
            ),
        )
    }

    private fun isCurrent(expectedGeneration: Long): Boolean = synchronized(lock) {
        generation == expectedGeneration && !stopped
    }

    private fun cancelScheduledTasksLocked() {
        reconnectFuture?.cancel(false)
        heartbeatFuture?.cancel(false)
        reconnectFuture = null
        heartbeatFuture = null
    }

    private fun emitState(state: ConnectionState) {
        listener.onStateChanged(state)
    }

    private inner class SocketListener(
        private val expectedGeneration: Long,
    ) : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            if (!isCurrent(expectedGeneration)) {
                webSocket.cancel()
                return
            }
            emitState(ConnectionState(ConnectionPhase.REGISTERING))
            sendRegistration(webSocket, expectedGeneration)
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            handleMessage(webSocket, expectedGeneration, text)
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(code, reason)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            handleDisconnected(expectedGeneration, "اتصال بسته شد: $code $reason")
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            handleDisconnected(expectedGeneration, t.message ?: "خطای اتصال")
        }
    }

    private companion object {
        const val NORMAL_CLOSURE_CODE: Int = 1000
        const val MESSAGE_TOO_BIG_CLOSURE_CODE: Int = 1009
        const val MAX_OUTBOUND_QUEUE_SIZE: Int = 100
        const val MIN_HEARTBEAT_SECONDS: Int = 5
        const val MAX_HEARTBEAT_SECONDS: Int = 300

        fun isUuid(value: String): Boolean = runCatching { UUID.fromString(value) }.isSuccess
    }
}
