package ai.simorgh.android.device

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings

object BackgroundLaunchAccess {
    fun isGranted(context: Context): Boolean = Settings.canDrawOverlays(context)

    fun canLaunchNow(context: Context): Boolean =
        SimorghAppVisibility.isVisible() || isGranted(context)

    fun openSettings(context: Context) {
        val applicationContext = context.applicationContext
        val candidates = listOf(
            Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:${applicationContext.packageName}"),
            ),
            Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION),
            Intent(Settings.ACTION_SETTINGS),
        )

        candidates.firstOrNull { intent ->
            runCatching {
                applicationContext.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }.onFailure { error ->
                if (error !is ActivityNotFoundException && error !is SecurityException) {
                    throw error
                }
            }.isSuccess
        }
    }
}
