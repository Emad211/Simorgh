package ai.simorgh.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import ai.simorgh.android.ui.SimorghApp
import ai.simorgh.android.ui.SimorghViewModel
import ai.simorgh.android.ui.theme.SimorghTheme

class MainActivity : ComponentActivity() {
    private val viewModel: SimorghViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            SimorghTheme {
                SimorghApp(viewModel = viewModel)
            }
        }
    }
}
