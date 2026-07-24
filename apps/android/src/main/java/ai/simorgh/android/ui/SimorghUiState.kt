package ai.simorgh.android.ui

import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.device.DeviceCapabilities
import ai.simorgh.android.transport.ConnectionState

data class SimorghUiState(
    val capabilities: DeviceCapabilities,
    val endpoint: String,
    val deviceToken: String = "",
    val serviceRunning: Boolean = false,
    val startOnBootEnabled: Boolean = false,
    val connectionState: ConnectionState = ConnectionState.Disconnected,
    val lastProtocolEvent: String? = null,
    val accessibilityEnabled: Boolean = false,
    val accessibilityServiceConnected: Boolean = false,
    val accessibilitySnapshot: AccessibilitySnapshot? = null,
    val accessibilityError: String? = null,
    val backgroundLaunchSpecialAccessRequired: Boolean = false,
    val backgroundLaunchAccessGranted: Boolean = false,
)
