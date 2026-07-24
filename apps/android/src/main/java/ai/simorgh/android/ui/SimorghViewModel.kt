package ai.simorgh.android.ui

import android.app.Application
import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.AndroidViewModel
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
        ),
    )
    val uiState: State<SimorghUiState> = mutableUiState

    private val statusSubscription: Closeable = ConnectionStatusBus.subscribe { snapshot ->
        mainHandler.post {
            mutableUiState.value = mutableUiState.value.copy(
                serviceRunning = snapshot.serviceRunning,
                connectionState = snapshot.connectionState,
                lastProtocolEvent = snapshot.lastProtocolEvent,
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
        statusSubscription.close()
        super.onCleared()
    }
}
