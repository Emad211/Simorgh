package ai.simorgh.android.device

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings

object BackgroundLaunchAccess {
    fun requiresSpecialAccess(): Boolean =
        BackgroundLaunchPolicy.requiresSpecialAccess(Build.VERSION.SDK_INT)

    fun isOverlayGranted(context: Context): Boolean =
        Settings.canDrawOverlays(context)

    fun isConfiguredForBackground(context: Context): Boolean =
        BackgroundLaunchPolicy.canLaunch(
            sdkInt = Build.VERSION.SDK_INT,
            appVisible = false,
            overlayGranted = isOverlayGranted(context),
        )

    fun canLaunchNow(context: Context): Boolean =
        BackgroundLaunchPolicy.canLaunch(
            sdkInt = Build.VERSION.SDK_INT,
            appVisible = SimorghAppVisibility.isVisible(),
            overlayGranted = isOverlayGranted(context),
        )

    fun openSettings(context: Context) {
        if (!requiresSpecialAccess()) {
            return
        }
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
