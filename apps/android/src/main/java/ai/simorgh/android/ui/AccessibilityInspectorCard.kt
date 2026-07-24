package ai.simorgh.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import ai.simorgh.android.R
import ai.simorgh.android.accessibility.AccessibilityNodeSnapshot

@Composable
fun AccessibilityInspectorCard(
    state: SimorghUiState,
    onOpenSettings: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = stringResource(R.string.accessibility_title),
                style = MaterialTheme.typography.titleLarge,
            )
            Text(
                text = when {
                    state.accessibilityServiceConnected ->
                        stringResource(R.string.accessibility_connected)
                    state.accessibilityEnabled ->
                        stringResource(R.string.accessibility_enabled_waiting)
                    else ->
                        stringResource(R.string.accessibility_disabled)
                },
                style = MaterialTheme.typography.titleMedium,
            )

            OutlinedButton(
                onClick = onOpenSettings,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(stringResource(R.string.accessibility_open_settings))
            }

            state.accessibilityError?.takeIf(String::isNotBlank)?.let { error ->
                Text(text = error, style = MaterialTheme.typography.bodySmall)
            }

            val snapshot = state.accessibilitySnapshot
            if (snapshot == null) {
                Text(
                    text = stringResource(R.string.accessibility_no_snapshot),
                    style = MaterialTheme.typography.bodyMedium,
                )
                return@Column
            }

            HorizontalDivider()
            InspectorStatusRow(
                label = stringResource(R.string.accessibility_active_package),
                value = snapshot.activePackage ?: "—",
            )
            InspectorStatusRow(
                label = stringResource(R.string.accessibility_node_count),
                value = snapshot.nodes.size.toString(),
            )
            InspectorStatusRow(
                label = stringResource(R.string.accessibility_window_count),
                value = snapshot.windows.size.toString(),
            )

            if (snapshot.truncated) {
                Text(
                    text = stringResource(R.string.accessibility_snapshot_truncated) +
                        ": ${snapshot.truncationReasons.joinToString()}",
                    style = MaterialTheme.typography.bodySmall,
                )
            }

            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = stringResource(R.string.accessibility_tree_preview),
                style = MaterialTheme.typography.labelLarge,
            )
            snapshot.nodes.take(MAX_PREVIEW_NODES).forEach { node ->
                Text(
                    text = nodePreview(node),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun InspectorStatusRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(text = label, style = MaterialTheme.typography.labelLarge)
        Text(text = value, style = MaterialTheme.typography.bodyMedium)
    }
}

private fun nodePreview(node: AccessibilityNodeSnapshot): String {
    val className = node.className?.substringAfterLast('.') ?: "Node"
    val semanticLabel: String = when {
        node.password -> "<password>"
        !node.text.isNullOrBlank() -> node.text
        !node.contentDescription.isNullOrBlank() -> node.contentDescription
        !node.viewId.isNullOrBlank() -> node.viewId
        else -> ""
    }
    val suffix = if (semanticLabel.isBlank()) "" else " — $semanticLabel"
    return "[${node.path}] $className$suffix"
}

private const val MAX_PREVIEW_NODES = 30
