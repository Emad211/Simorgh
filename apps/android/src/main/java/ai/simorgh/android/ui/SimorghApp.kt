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
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalLayoutDirection
import ai.simorgh.android.R
import ai.simorgh.android.device.DeviceCapabilities

@Composable
fun SimorghApp(capabilities: DeviceCapabilities) {
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

                ConnectionCard()
                DeviceCard(capabilities)
            }
        }
    }
}

@Composable
private fun ConnectionCard() {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = stringResource(R.string.connection_disconnected),
                style = MaterialTheme.typography.titleMedium,
            )
            Text(
                text = stringResource(R.string.connection_hint),
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
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
