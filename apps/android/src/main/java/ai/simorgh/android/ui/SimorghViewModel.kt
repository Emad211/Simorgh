package ai.simorgh.android.ui

import android.app.Application
import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.AndroidViewModel
import ai.simorgh.android.accessibility.AccessibilityObservationBus
import ai.simorgh.android.accessibility.AccessibilityServiceStatus
import ai.simorgh.android.device.BackgroundLaunchAccess
import ai.simorgh.android.device.DeviceCapabilities
import ai.simorgh.android.service.ConnectionStatusBus
import ai.simorgh.android.service.SecureConnectionStore
import ai.simorgh.android.service.SimorghConnectionService
import ai.simorgh.android.transport.ConnectionPhase
import ai.simorgh.android.transport.ConnectionState
import ai.simorgh.android.transport.CoreConnectionConfig
import ai.simorgh.android.transport.CoreConnectionPreferences
import java.io.Closeable

class SimorghViewModel(application: Application) : AndroidViewModel(application) {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val connectionPreferences = CoreConnectionPreferences(application)
    private val secureConnectionStore = SecureConnectionStore(application)

    private val mutableUiState = mutableStateOf(
        SimorghUiState(
            capabilities = DeviceCapabilities.current(),
            endpoint = secureConnectionStore.load()?.endpoint
                ?: connectionPreferences.loadEndpoint(),
            startOnBootEnabled = secureConnectionStore.isStartOnBootEnabled(),
            accessibilityEnabled = AccessibilityServiceStatus.isEnabled(application),
            backgroundLaunchSpecialAccessRequired =
                BackgroundLaunchAccess.requiresSpecialAccess(),
            backgroundLaunchAccessGranted =
                BackgroundLaunchAccess.isConfiguredForBackground(application),
        ),
    )
    val uiState: State<SimorghUiState> = mutableUiState

    private val connectionStatusSubscription: Closeable = ConnectionStatusBus.subscribe { snapshot ->
        mainHandler.post {
            mutableUiState.value = mutableUiState.value.copy(
                serviceRunning = snapshot.serviceRunning,
                connectionState = snapshot.connectionState,
                lastProtocolEvent = snapshot.lastProtocolEvent,
            )
        }
    }

    private val accessibilityStatusSubscription: Closeable =
        AccessibilityObservationBus.subscribe { observerState ->
            mainHandler.post {
                val currentState = mutableUiState.value
                val observedSnapshot = observerState.latestSnapshot
                    ?.takeUnless { it.activePackage == application.packageName }
                    ?: currentState.accessibilitySnapshot
                mutableUiState.value = currentState.copy(
                    accessibilityEnabled = observerState.serviceConnected ||
                        AccessibilityServiceStatus.isEnabled(application),
                    accessibilityServiceConnected = observerState.serviceConnected,
                    accessibilitySnapshot = observedSnapshot,
                    accessibilityError = observerState.lastError,
                )
            }
        }

    fun updateEndpoint(endpoint: String) {
        mutableUiState.value = mutableUiState.value.copy(endpoint = endpoint)
    }

    fun updateDeviceToken(token: String) {
        mutableUiState.value = mutableUiState.value.copy(deviceToken = token)
    }

    fun updateStartOnBoot(enabled: Boolean) {
        secureConnectionStore.setStartOnBootEnabled(enabled)
        mutableUiState.value = mutableUiState.value.copy(startOnBootEnabled = enabled)
    }

    fun refreshAccessibilityStatus() {
        mutableUiState.value = mutableUiState.value.copy(
            accessibilityEnabled = AccessibilityServiceStatus.isEnabled(getApplication()),
        )
    }

    fun openAccessibilitySettings() {
        AccessibilityServiceStatus.openSystemSettings(getApplication())
    }

    fun refreshBackgroundLaunchAccess() {
        mutableUiState.value = mutableUiState.value.copy(
            backgroundLaunchSpecialAccessRequired =
                BackgroundLaunchAccess.requiresSpecialAccess(),
            backgroundLaunchAccessGranted =
                BackgroundLaunchAccess.isConfiguredForBackground(getApplication()),
        )
    }

    fun openBackgroundLaunchAccessSettings() {
        BackgroundLaunchAccess.openSettings(getApplication())
    }

    fun connect() {
        val state = mutableUiState.value
        val enteredToken = state.deviceToken.trim()
        val savedConfig = secureConnectionStore.load()
        val token = enteredToken.ifBlank { savedConfig?.deviceToken.orEmpty() }
        val config = runCatching {
            CoreConnectionConfig(
                endpoint = state.endpoint,
                deviceToken = token,
            ).validated()
        }.getOrElse { error ->
            mutableUiState.value = state.copy(
                connectionState = ConnectionState(
                    phase = ConnectionPhase.FAILED,
                    detail = error.message ?: "تنظیمات اتصال معتبر نیست",
                ),
            )
            return
        }

        connectionPreferences.saveEndpoint(config.endpoint)
        mutableUiState.value = state.copy(
            endpoint = config.endpoint,
            deviceToken = "",
            lastProtocolEvent = null,
        )
        SimorghConnectionService.start(getApplication(), config)
    }

    fun disconnect() {
        SimorghConnectionService.stop(getApplication())
    }

    override fun onCleared() {
        connectionStatusSubscription.close()
        accessibilityStatusSubscription.close()
        super.onCleared()
    }
}
