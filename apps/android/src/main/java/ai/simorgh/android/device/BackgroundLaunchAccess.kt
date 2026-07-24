package ai.simorgh.android.device

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings

object BackgroundLaunchAccess {
    fun isGranted(context: Context): Boolean = Settings.canDrawOverlays(context)

    fun canLaunchNow(context: Context): Boolean =
        SimorghAppVisibility.isVisible() || isGranted(context)

    fun openSettings(context: Context) {
        val intent = Intent(
            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
            Uri.parse("package:${context.packageName}"),
        ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }
}
