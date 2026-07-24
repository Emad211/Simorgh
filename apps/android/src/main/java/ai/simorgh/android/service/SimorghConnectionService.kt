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
import ai.simorgh.android.device.DeviceCapabilities
import ai.simorgh.android.device.DeviceIdentityStore
import ai.simorgh.android.transport.ConnectionPhase
import ai.simorgh.android.transport.ConnectionState
import ai.simorgh.android.transport.CoreConnectionConfig
import ai.simorgh.android.transport.CoreConnectionListener
import ai.simorgh.android.transport.CoreWebSocketClient

class SimorghConnectionService : Service(), CoreConnectionListener {
    private val mainHandler = Handler(Looper.getMainLooper())

    private lateinit var connectionStore: SecureConnectionStore
    private lateinit var connectionClient: CoreWebSocketClient
    private lateinit var notificationManager: NotificationManager

    private var currentState: ConnectionState = ConnectionState.Disconnected
    private var lastProtocolEvent: String? = null
    private var foregroundStarted = false

    override fun onCreate() {
        super.onCreate()
        connectionStore = SecureConnectionStore(this)
        notificationManager = getSystemService(NotificationManager::class.java)
        createNotificationChannel()

        val capabilities = DeviceCapabilities.current()
        connectionClient = CoreWebSocketClient(
            deviceId = DeviceIdentityStore(this).getOrCreateDeviceId(),
            capabilities = capabilities,
            listener = this,
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            connectionStore.setAutoResumeEnabled(false)
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
            else -> connectionStore.loadForAutoResume()
        }

        if (config == null) {
            publishFailure(getString(R.string.service_missing_configuration))
            stopConnectionAndService()
            return START_NOT_STICKY
        }

        if (intent?.action == ACTION_START) {
            connectionStore.save(config, autoResume = true)
        }
        connectionClient.connect(config)
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
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
            SecureConnectionStore(context).setAutoResumeEnabled(false)
            context.stopService(Intent(context, SimorghConnectionService::class.java))
        }
    }
}
