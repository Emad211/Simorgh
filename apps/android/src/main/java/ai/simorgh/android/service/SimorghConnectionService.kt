package ai.simorgh.android.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import ai.simorgh.android.MainActivity
import ai.simorgh.android.R
import ai.simorgh.android.accessibility.AccessibilityAcknowledgementBus
import ai.simorgh.android.accessibility.AccessibilityObservationBus
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotProjection
import ai.simorgh.android.actions.AccessibilityActionEvidenceSource
import ai.simorgh.android.actions.AndroidActionCommand
import ai.simorgh.android.actions.AndroidActionHandlerRegistry
import ai.simorgh.android.actions.AndroidActionRouter
import ai.simorgh.android.actions.AndroidOpenAppLauncher
import ai.simorgh.android.actions.OpenAppActionExecutor
import ai.simorgh.android.actions.PersistentActionLedger
import ai.simorgh.android.device.DeviceCapabilities
import ai.simorgh.android.device.DeviceIdentityStore
import ai.simorgh.android.protocol.ActionResultAckStatus
import ai.simorgh.android.protocol.DeviceActionCancelPayload
import ai.simorgh.android.protocol.DeviceActionResultAckPayload
import ai.simorgh.android.protocol.DeviceObservationAckPayload
import ai.simorgh.android.protocol.DeviceObservationRefreshPayload
import ai.simorgh.android.protocol.DeviceProtocol
import ai.simorgh.android.protocol.ObservationRefreshAckStatus
import ai.simorgh.android.protocol.ObservationRefreshProtocol
import ai.simorgh.android.protocol.ProtocolEnvelope
import ai.simorgh.android.transport.AccessibilityObservationPublisher
import ai.simorgh.android.transport.AccessibilityRefreshCoordinator
import ai.simorgh.android.transport.ActionResultPublisher
import ai.simorgh.android.transport.ConnectionPhase
import ai.simorgh.android.transport.ConnectionState
import ai.simorgh.android.transport.CoreConnectionConfig
import ai.simorgh.android.transport.CoreConnectionListener
import ai.simorgh.android.transport.CoreWebSocketClient
import java.io.Closeable
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

class SimorghConnectionService : Service(), CoreConnectionListener {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val observationExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    private val latestObservation = AtomicReference<AccessibilitySnapshot?>(null)
    private val observationDrainScheduled = AtomicBoolean(false)

    private lateinit var connectionStore: SecureConnectionStore
    private lateinit var connectionClient: CoreWebSocketClient
    private lateinit var observationPublisher: AccessibilityObservationPublisher
    private lateinit var refreshCoordinator: AccessibilityRefreshCoordinator
    private lateinit var actionResultPublisher: ActionResultPublisher
    private lateinit var actionRouter: AndroidActionRouter
    private lateinit var openAppExecutor: OpenAppActionExecutor
    private lateinit var actionHandlerInstallation: Closeable
    private lateinit var observationSubscription: Closeable
    private lateinit var notificationManager: NotificationManager
    private lateinit var deviceId: String

    private var currentState: ConnectionState = ConnectionState.Disconnected
    private var lastProtocolEvent: String? = null
    private var foregroundStarted = false

    override fun onCreate() {
        super.onCreate()
        connectionStore = SecureConnectionStore(this)
        notificationManager = getSystemService(NotificationManager::class.java)
        createNotificationChannel()
        AccessibilityAcknowledgementBus.reset()

        val capabilities = DeviceCapabilities.current()
        deviceId = DeviceIdentityStore(this).getOrCreateDeviceId()
        val snapshotProjector: (AccessibilitySnapshot) -> AccessibilitySnapshot = { snapshot ->
            AccessibilitySnapshotProjection.forDeviceTransport(
                snapshot = snapshot,
                simorghPackageName = packageName,
            )
        }
        connectionClient = CoreWebSocketClient(
            deviceId = deviceId,
            capabilities = capabilities,
            listener = this,
        )
        observationPublisher = AccessibilityObservationPublisher(
            deviceId = deviceId,
            sender = connectionClient::send,
            listener = ::onProtocolEvent,
            acknowledgementListener = AccessibilityAcknowledgementBus::publish,
        )
        refreshCoordinator = AccessibilityRefreshCoordinator(
            publisher = observationPublisher,
            snapshotProjector = snapshotProjector,
            terminalAcknowledgementEmitter = ::sendObservationRefreshAcknowledgement,
        )
        actionResultPublisher = ActionResultPublisher(
            deviceId = deviceId,
            sender = connectionClient::send,
            listener = ::onProtocolEvent,
        )
        openAppExecutor = OpenAppActionExecutor(
            launcher = AndroidOpenAppLauncher(this),
            evidenceSource = AccessibilityActionEvidenceSource(
                snapshotProjector = snapshotProjector,
            ),
        )
        actionHandlerInstallation = AndroidActionHandlerRegistry.install(openAppExecutor)
        actionRouter = AndroidActionRouter(
            ledger = PersistentActionLedger(this),
            resultEmitter = { delivery ->
                if (!actionResultPublisher.submit(delivery)) {
                    onProtocolEvent(
                        "نتیجه فرمان ${delivery.result.actionId} وارد صف ارسال نشد",
                    )
                }
            },
            eventListener = ::onProtocolEvent,
        )
        actionRouter.recoverUnacknowledgedResult()

        observationSubscription = AccessibilityObservationBus.subscribe { observerState ->
            val snapshot = observerState.latestSnapshot ?: return@subscribe
            enqueueLatestObservation(snapshotProjector(snapshot))
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            connectionStore.setConnectionEnabled(false)
            stopConnectionAndService()
            return START_NOT_STICKY
        }

        promoteToForeground(
            ConnectionState(
                phase = ConnectionPhase.CONNECTING,
                detail = getString(R.string.service_initializing),
            ),
        )

        val config = when (intent?.action) {
            ACTION_START -> configFromIntent(intent)
            else -> connectionStore.loadForServiceResume()
        }

        if (config == null) {
            publishFailure(getString(R.string.service_missing_configuration))
            stopConnectionAndService()
            return START_NOT_STICKY
        }

        if (intent?.action == ACTION_START) {
            connectionStore.save(config, connectionEnabled = true)
        }
        connectionClient.connect(config)
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        actionHandlerInstallation.close()
        openAppExecutor.close()
        refreshCoordinator.close()
        observationSubscription.close()
        latestObservation.set(null)
        observationExecutor.shutdownNow()
        observationPublisher.close()
        AccessibilityAcknowledgementBus.reset()
        actionResultPublisher.close()
        connectionClient.close()
        ConnectionStatusBus.publish(
            ServiceConnectionSnapshot(
                serviceRunning = false,
                connectionState = ConnectionState.Disconnected,
                lastProtocolEvent = lastProtocolEvent,
            ),
        )
        super.onDestroy()
    }

    override fun onStateChanged(state: ConnectionState) {
        val connected = state.phase == ConnectionPhase.CONNECTED
        observationPublisher.setConnected(connected)
        actionResultPublisher.setConnected(connected)
        if (connected) {
            actionRouter.recoverUnacknowledgedResult()
        }
        mainHandler.post {
            currentState = state
            publishSnapshot()
            if (foregroundStarted) {
                notificationManager.notify(NOTIFICATION_ID, buildNotification(state))
            }
        }
    }

    override fun onProtocolEvent(detail: String) {
        mainHandler.post {
            lastProtocolEvent = detail
            publishSnapshot()
        }
    }

    override fun onObservationAcknowledged(
        acknowledgement: DeviceObservationAckPayload,
        correlationId: String?,
    ) {
        observationPublisher.acknowledge(
            acknowledgement = acknowledgement,
            correlationId = correlationId,
        )
    }

    override fun onObservationRefreshRequest(
        requestEnvelopeId: String,
        payload: DeviceObservationRefreshPayload,
    ) {
        val receipt = refreshCoordinator.receive(
            requestEnvelopeId = requestEnvelopeId,
            rawPayload = payload,
        )
        sendObservationRefreshAcknowledgement(
            requestId = requestEnvelopeId,
            status = receipt.status,
            detail = receipt.detail,
        )
    }

    override fun onActionCommand(
        commandEnvelopeId: String,
        command: AndroidActionCommand,
    ) {
        val receipt = actionRouter.receiveCommand(
            commandEnvelopeId = commandEnvelopeId,
            rawCommand = command,
        )
        sendProtocolEnvelope(
            DeviceProtocol.actionCommandAck(
                deviceId = deviceId,
                commandEnvelopeId = commandEnvelopeId,
                command = command,
                status = receipt.status,
                detail = receipt.detail,
            ),
            event = "پاسخ دریافت فرمان Android",
        )
    }

    override fun onActionCancellation(
        cancelEnvelopeId: String,
        cancellation: DeviceActionCancelPayload,
    ) {
        val status = actionRouter.receiveCancellation(cancellation)
        sendProtocolEnvelope(
            DeviceProtocol.actionCancelAck(
                deviceId = deviceId,
                cancelEnvelopeId = cancelEnvelopeId,
                cancellation = cancellation,
                status = status,
            ),
            event = "پاسخ لغو فرمان Android",
        )
    }

    override fun onActionResultAcknowledged(
        acknowledgement: DeviceActionResultAckPayload,
        correlationId: String?,
    ) {
        val ledgerAccepted = runCatching {
            actionRouter.acknowledgeResult(
                acknowledgement = acknowledgement,
                correlationId = correlationId,
            )
        }.getOrElse { error ->
            onProtocolEvent(
                "ثبت ACK نتیجه فرمان شکست خورد: ${error.javaClass.simpleName}",
            )
            false
        }

        val terminalRejection = acknowledgement.status == ActionResultAckStatus.UNKNOWN_ACTION ||
            acknowledgement.status == ActionResultAckStatus.REJECTED
        val publisherAccepted = if (ledgerAccepted || terminalRejection) {
            actionResultPublisher.acknowledge(
                acknowledgement = acknowledgement,
                correlationId = correlationId,
            )
        } else {
            false
        }

        if (!publisherAccepted) {
            onProtocolEvent("ACK نتیجه فرمان با پیام درحال‌ارسال تطبیق نداشت")
        }
    }

    private fun sendObservationRefreshAcknowledgement(
        requestId: String,
        status: ObservationRefreshAckStatus,
        detail: String,
    ) {
        val acknowledgement = runCatching {
            ObservationRefreshProtocol.acknowledgement(
                deviceId = deviceId,
                requestEnvelopeId = requestId,
                requestId = requestId,
                status = status,
                detail = detail,
            )
        }.getOrElse { error ->
            onProtocolEvent(
                "ساخت ACK تازه‌سازی Observation شکست خورد: ${error.javaClass.simpleName}",
            )
            return
        }
        sendProtocolEnvelope(
            acknowledgement,
            event = "پاسخ تازه‌سازی Observation",
        )
    }

    private fun sendProtocolEnvelope(envelope: ProtocolEnvelope, event: String) {
        if (!connectionClient.send(envelope)) {
            onProtocolEvent("$event ارسال نشد")
        }
    }

    private fun enqueueLatestObservation(snapshot: AccessibilitySnapshot) {
        latestObservation.set(snapshot)
        if (observationDrainScheduled.compareAndSet(false, true)) {
            observationExecutor.execute(::drainLatestObservations)
        }
    }

    private fun drainLatestObservations() {
        while (true) {
            val snapshot = latestObservation.getAndSet(null) ?: break
            observationPublisher.submit(snapshot)
        }
        observationDrainScheduled.set(false)
        if (
            latestObservation.get() != null &&
            observationDrainScheduled.compareAndSet(false, true)
        ) {
            observationExecutor.execute(::drainLatestObservations)
        }
    }

    private fun configFromIntent(intent: Intent): CoreConnectionConfig? {
        val endpoint = intent.getStringExtra(EXTRA_ENDPOINT) ?: return null
        val token = intent.getStringExtra(EXTRA_DEVICE_TOKEN) ?: return null
        return runCatching {
            CoreConnectionConfig(endpoint = endpoint, deviceToken = token).validated()
        }.getOrNull()
    }

    private fun promoteToForeground(state: ConnectionState) {
        currentState = state
        val notification = buildNotification(state)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
        foregroundStarted = true
        publishSnapshot()
    }

    private fun buildNotification(state: ConnectionState): Notification {
        val openAppIntent = PendingIntent.getActivity(
            this,
            OPEN_APP_REQUEST_CODE,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stopIntent = PendingIntent.getService(
            this,
            STOP_SERVICE_REQUEST_CODE,
            Intent(this, SimorghConnectionService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, NOTIFICATION_CHANNEL_ID)
        } else {
            Notification.Builder(this)
        }

        return builder
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle(getString(R.string.service_notification_title))
            .setContentText(notificationText(state))
            .setContentIntent(openAppIntent)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .addAction(
                android.R.drawable.ic_menu_close_clear_cancel,
                getString(R.string.disconnect_action),
                stopIntent,
            )
            .build()
    }

    private fun notificationText(state: ConnectionState): String = when (state.phase) {
        ConnectionPhase.DISCONNECTED -> getString(R.string.connection_disconnected)
        ConnectionPhase.CONNECTING -> getString(R.string.connection_connecting)
        ConnectionPhase.REGISTERING -> getString(R.string.connection_registering)
        ConnectionPhase.CONNECTED -> getString(R.string.connection_connected)
        ConnectionPhase.RETRY_WAIT -> getString(
            R.string.connection_retry_wait,
            state.reconnectAttempt,
        )
        ConnectionPhase.FAILED -> getString(R.string.connection_failed)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return
        }
        val channel = NotificationChannel(
            NOTIFICATION_CHANNEL_ID,
            getString(R.string.service_notification_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = getString(R.string.service_notification_channel_description)
            setShowBadge(false)
        }
        notificationManager.createNotificationChannel(channel)
    }

    private fun publishSnapshot() {
        ConnectionStatusBus.publish(
            ServiceConnectionSnapshot(
                serviceRunning = true,
                connectionState = currentState,
                lastProtocolEvent = lastProtocolEvent,
            ),
        )
    }

    private fun publishFailure(detail: String) {
        currentState = ConnectionState(
            phase = ConnectionPhase.FAILED,
            detail = detail,
        )
        publishSnapshot()
        if (foregroundStarted) {
            notificationManager.notify(NOTIFICATION_ID, buildNotification(currentState))
        }
    }

    private fun stopConnectionAndService() {
        connectionClient.disconnect()
        if (foregroundStarted) {
            stopForeground(STOP_FOREGROUND_REMOVE)
            foregroundStarted = false
        }
        stopSelf()
    }

    companion object {
        const val ACTION_START = "ai.simorgh.android.action.START_CONNECTION"
        const val ACTION_STOP = "ai.simorgh.android.action.STOP_CONNECTION"

        private const val EXTRA_ENDPOINT = "core_endpoint"
        private const val EXTRA_DEVICE_TOKEN = "device_token"
        private const val NOTIFICATION_CHANNEL_ID = "simorgh_connection"
        private const val NOTIFICATION_ID = 1001
        private const val OPEN_APP_REQUEST_CODE = 1001
        private const val STOP_SERVICE_REQUEST_CODE = 1002

        fun start(context: Context, config: CoreConnectionConfig) {
            val validated = config.validated()
            val intent = Intent(context, SimorghConnectionService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_ENDPOINT, validated.endpoint)
                .putExtra(EXTRA_DEVICE_TOKEN, validated.deviceToken)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            SecureConnectionStore(context).setConnectionEnabled(false)
            context.stopService(Intent(context, SimorghConnectionService::class.java))
        }
    }
}
