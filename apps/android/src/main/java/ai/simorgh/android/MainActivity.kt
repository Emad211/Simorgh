package ai.simorgh.android

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import ai.simorgh.android.device.SimorghAppVisibility
import ai.simorgh.android.ui.SimorghApp
import ai.simorgh.android.ui.SimorghViewModel
import ai.simorgh.android.ui.theme.SimorghTheme

class MainActivity : ComponentActivity() {
    private val viewModel: SimorghViewModel by viewModels()

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) {
        viewModel.connect()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            SimorghTheme {
                SimorghApp(
                    viewModel = viewModel,
                    onConnectRequested = ::connectWithNotificationPermission,
                )
            }
        }
    }

    override fun onStart() {
        super.onStart()
        SimorghAppVisibility.onActivityStarted()
    }

    override fun onResume() {
        super.onResume()
        viewModel.refreshAccessibilityStatus()
        viewModel.refreshBackgroundLaunchAccess()
    }

    override fun onStop() {
        SimorghAppVisibility.onActivityStopped()
        super.onStop()
    }

    private fun connectWithNotificationPermission() {
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            viewModel.connect()
        }
    }
}
