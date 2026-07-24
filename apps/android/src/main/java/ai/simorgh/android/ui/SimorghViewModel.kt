package ai.simorgh.android.ui

import android.app.Application
import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.AndroidViewModel
import ai.simorgh.android.device.DeviceCapabilities
import ai.simorgh.android.device.DeviceIdentityStore
import ai.simorgh.android.transport.ConnectionPhase
import ai.simorgh.android.transport.ConnectionState
import ai.simorgh.android.transport.CoreConnectionConfig
import ai.simorgh.android.transport.CoreConnectionListener
import ai.simorgh.android.transport.CoreConnectionPreferences
import ai.simorgh.android.transport.CoreWebSocketClient

class SimorghViewModel(application: Application) : AndroidViewModel(application) {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val capabilities = DeviceCapabilities.current()
    private val identityStore = DeviceIdentityStore(application)
    private val connectionPreferences = CoreConnectionPreferences(application)
    private val deviceId = identityStore.getOrCreateDeviceId()

    private val mutableUiState = mutableStateOf(
        SimorghUiState(
            capabilities = capabilities,
            endpoint = connectionPreferences.loadEndpoint(),
        ),
    )
    val uiState: State<SimorghUiState> = mutableUiState

    private val connectionClient = CoreWebSocketClient(
        deviceId = deviceId,
        capabilities = capabilities,
        listener = object : CoreConnectionListener {
            override fun onStateChanged(state: ConnectionState) {
                mainHandler.post {
                    mutableUiState.value = mutableUiState.value.copy(connectionState = state)
                }
            }

            override fun onProtocolEvent(detail: String) {
                mainHandler.post {
                    mutableUiState.value = mutableUiState.value.copy(lastProtocolEvent = detail)
                }
            }
        },
    )

    fun updateEndpoint(endpoint: String) {
        mutableUiState.value = mutableUiState.value.copy(endpoint = endpoint)
    }

    fun updateDeviceToken(token: String) {
        mutableUiState.value = mutableUiState.value.copy(deviceToken = token)
    }

    fun connect() {
        val state = mutableUiState.value
        val config = runCatching {
            CoreConnectionConfig(
                endpoint = state.endpoint,
                deviceToken = state.deviceToken,
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
            lastProtocolEvent = null,
        )
        connectionClient.connect(config)
    }

    fun disconnect() {
        connectionClient.disconnect()
    }

    override fun onCleared() {
        connectionClient.close()
        super.onCleared()
    }
}
