package ai.simorgh.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import ai.simorgh.android.R

@Composable
fun BackgroundLaunchAccessCard(
    granted: Boolean,
    onOpenSettings: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = stringResource(R.string.background_launch_title),
                style = MaterialTheme.typography.titleLarge,
            )
            Text(
                text = stringResource(
                    if (granted) {
                        R.string.background_launch_granted
                    } else {
                        R.string.background_launch_missing
                    },
                ),
                style = MaterialTheme.typography.titleMedium,
            )
            Text(
                text = stringResource(R.string.background_launch_explanation),
                style = MaterialTheme.typography.bodyMedium,
            )
            if (!granted) {
                OutlinedButton(
                    onClick = onOpenSettings,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(stringResource(R.string.background_launch_open_settings))
                }
            }
        }
    }
}
