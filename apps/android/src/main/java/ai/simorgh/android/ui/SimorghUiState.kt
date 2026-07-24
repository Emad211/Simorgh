package ai.simorgh.android.ui

import ai.simorgh.android.device.DeviceCapabilities
import ai.simorgh.android.transport.ConnectionState

data class SimorghUiState(
    val capabilities: DeviceCapabilities,
    val endpoint: String,
    val deviceToken: String = "",
    val connectionState: ConnectionState = ConnectionState.Disconnected,
    val lastProtocolEvent: String? = null,
)
