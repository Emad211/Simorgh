package ai.simorgh.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import ai.simorgh.android.device.DeviceCapabilities
import ai.simorgh.android.ui.SimorghApp
import ai.simorgh.android.ui.theme.SimorghTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            SimorghTheme {
                SimorghApp(capabilities = DeviceCapabilities.current())
            }
        }
    }
}
