package ai.simorgh.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import ai.simorgh.android.R
import ai.simorgh.android.device.DeviceCapabilities
import ai.simorgh.android.transport.ConnectionPhase
import ai.simorgh.android.transport.ConnectionState

@Composable
fun SimorghApp(
    viewModel: SimorghViewModel,
    onConnectRequested: () -> Unit,
) {
    val state = viewModel.uiState.value
    SimorghApp(
        state = state,
        onEndpointChanged = viewModel::updateEndpoint,
        onDeviceTokenChanged = viewModel::updateDeviceToken,
        onStartOnBootChanged = viewModel::updateStartOnBoot,
        onConnect = onConnectRequested,
        onDisconnect = viewModel::disconnect,
    )
}

@Composable
private fun SimorghApp(
    state: SimorghUiState,
    onEndpointChanged: (String) -> Unit,
    onDeviceTokenChanged: (String) -> Unit,
    onStartOnBootChanged: (Boolean) -> Unit,
    onConnect: () -> Unit,
    onDisconnect: () -> Unit,
) {
    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier
                    .verticalScroll(rememberScrollState())
                    .padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                Text(
                    text = stringResource(R.string.app_name),
                    style = MaterialTheme.typography.displaySmall,
                )
                Text(
                    text = stringResource(R.string.foundation_ready),
                    style = MaterialTheme.typography.titleMedium,
                )

                ConnectionCard(
                    endpoint = state.endpoint,
                    token = state.deviceToken,
                    serviceRunning = state.serviceRunning,
                    startOnBootEnabled = state.startOnBootEnabled,
                    connectionState = state.connectionState,
                    lastProtocolEvent = state.lastProtocolEvent,
                    onEndpointChanged = onEndpointChanged,
                    onDeviceTokenChanged = onDeviceTokenChanged,
                    onStartOnBootChanged = onStartOnBootChanged,
                    onConnect = onConnect,
                    onDisconnect = onDisconnect,
                )
                DeviceCard(state.capabilities)
            }
        }
    }
}

@Composable
private fun ConnectionCard(
    endpoint: String,
    token: String,
    serviceRunning: Boolean,
    startOnBootEnabled: Boolean,
    connectionState: ConnectionState,
    lastProtocolEvent: String?,
    onEndpointChanged: (String) -> Unit,
    onDeviceTokenChanged: (String) -> Unit,
    onStartOnBootChanged: (Boolean) -> Unit,
    onConnect: () -> Unit,
    onDisconnect: () -> Unit,
) {
    val isBusyOrConnected = serviceRunning || connectionState.phase in setOf(
        ConnectionPhase.CONNECTING,
        ConnectionPhase.REGISTERING,
        ConnectionPhase.CONNECTED,
        ConnectionPhase.RETRY_WAIT,
    )

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = stringResource(R.string.connection_title),
                style = MaterialTheme.typography.titleLarge,
            )
            Text(
                text = connectionStateLabel(connectionState),
                style = MaterialTheme.typography.titleMedium,
            )

            OutlinedTextField(
                value = endpoint,
                onValueChange = onEndpointChanged,
                modifier = Modifier.fillMaxWidth(),
                enabled = !isBusyOrConnected,
                singleLine = true,
                label = { Text(stringResource(R.string.endpoint_label)) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                textStyle = LocalTextStyle.current.copy(textDirection = TextDirection.Ltr),
            )
            OutlinedTextField(
                value = token,
                onValueChange = onDeviceTokenChanged,
                modifier = Modifier.fillMaxWidth(),
                enabled = !isBusyOrConnected,
                singleLine = true,
                label = { Text(stringResource(R.string.device_token_label)) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                visualTransformation = PasswordVisualTransformation(),
                textStyle = LocalTextStyle.current.copy(textDirection = TextDirection.Ltr),
                supportingText = { Text(stringResource(R.string.device_token_hint)) },
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = stringResource(R.string.start_on_boot_label),
                        style = MaterialTheme.typography.bodyLarge,
                    )
                    Text(
                        text = stringResource(R.string.start_on_boot_hint),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Switch(
                    checked = startOnBootEnabled,
                    onCheckedChange = onStartOnBootChanged,
                )
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Button(
                    onClick = onConnect,
                    enabled = !isBusyOrConnected,
                    modifier = Modifier.weight(1f),
                ) {
                    Text(stringResource(R.string.connect_action))
                }
                OutlinedButton(
                    onClick = onDisconnect,
                    enabled = serviceRunning,
                    modifier = Modifier.weight(1f),
                ) {
                    Text(stringResource(R.string.disconnect_action))
                }
            }

            connectionState.detail?.takeIf { it.isNotBlank() }?.let { detail ->
                Text(text = detail, style = MaterialTheme.typography.bodySmall)
            }
            lastProtocolEvent?.takeIf { it.isNotBlank() }?.let { event ->
                Text(text = event, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun connectionStateLabel(state: ConnectionState): String = when (state.phase) {
    ConnectionPhase.DISCONNECTED -> stringResource(R.string.connection_disconnected)
    ConnectionPhase.CONNECTING -> stringResource(R.string.connection_connecting)
    ConnectionPhase.REGISTERING -> stringResource(R.string.connection_registering)
    ConnectionPhase.CONNECTED -> stringResource(R.string.connection_connected)
    ConnectionPhase.RETRY_WAIT -> stringResource(
        R.string.connection_retry_wait,
        state.reconnectAttempt,
    )
    ConnectionPhase.FAILED -> stringResource(R.string.connection_failed)
}

@Composable
private fun DeviceCard(capabilities: DeviceCapabilities) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(20.dp)) {
            Text(
                text = stringResource(R.string.status_title),
                style = MaterialTheme.typography.titleLarge,
            )
            Spacer(modifier = Modifier.height(12.dp))

            StatusRow(
                label = stringResource(R.string.protocol_label),
                value = capabilities.protocolVersion,
            )
            HorizontalDivider(modifier = Modifier.padding(vertical = 10.dp))
            StatusRow(
                label = stringResource(R.string.android_label),
                value = "${capabilities.androidRelease} (API ${capabilities.sdkInt})",
            )
            HorizontalDivider(modifier = Modifier.padding(vertical = 10.dp))
            StatusRow(
                label = stringResource(R.string.support_tier_label),
                value = capabilities.supportTier.name,
            )
            HorizontalDivider(modifier = Modifier.padding(vertical = 10.dp))
            StatusRow(
                label = stringResource(R.string.device_label),
                value = "${capabilities.manufacturer} ${capabilities.model}".trim(),
            )
            HorizontalDivider(modifier = Modifier.padding(vertical = 10.dp))
            Text(
                text = stringResource(R.string.capabilities_label),
                style = MaterialTheme.typography.labelLarge,
            )
            Spacer(modifier = Modifier.height(6.dp))
            capabilities.capabilities.sorted().forEach { capability ->
                Text(
                    text = "• $capability",
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
    }
}

@Composable
private fun StatusRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(text = label, style = MaterialTheme.typography.labelLarge)
        Text(text = value, style = MaterialTheme.typography.bodyMedium)
    }
}
