package ai.simorgh.android.actions

import android.app.ActivityOptions
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.IntentSender
import android.net.Uri
import android.os.Build
import ai.simorgh.android.device.BackgroundLaunchAccess

enum class OpenAppLaunchStatus {
    ACCEPTED,
    BACKGROUND_START_BLOCKED,
    TARGET_NOT_FOUND,
    INVALID_URI,
    REJECTED,
}

data class OpenAppLaunchAttempt(
    val status: OpenAppLaunchStatus,
    val adapter: String,
    val detail: String,
) {
    val accepted: Boolean
        get() = status == OpenAppLaunchStatus.ACCEPTED
}

fun interface OpenAppLauncher {
    fun launch(operation: OpenAppOperation): OpenAppLaunchAttempt
}

class AndroidOpenAppLauncher(
    context: Context,
    private val launchAllowed: () -> Boolean = {
        BackgroundLaunchAccess.canLaunchNow(context)
    },
) : OpenAppLauncher {
    private val applicationContext = context.applicationContext
    private val packageManager = applicationContext.packageManager

    override fun launch(operation: OpenAppOperation): OpenAppLaunchAttempt {
        if (operation.packageName == applicationContext.packageName) {
            return OpenAppLaunchAttempt(
                status = OpenAppLaunchStatus.REJECTED,
                adapter = "self_package_guard",
                detail = "Simorgh does not observe its own UI, so self-launch cannot be verified",
            )
        }
        if (!launchAllowed()) {
            return OpenAppLaunchAttempt(
                status = OpenAppLaunchStatus.BACKGROUND_START_BLOCKED,
                adapter = "background_launch_guard",
                detail = "Simorgh is not visible and display-over-other-apps access is not granted",
            )
        }

        return operation.uri?.let { uri ->
            launchExplicitUri(operation.packageName, uri)
        } ?: launchFrontDoor(operation.packageName)
    }

    private fun launchFrontDoor(packageName: String): OpenAppLaunchAttempt =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            launchWithIntentSender(packageName)
        } else {
            launchWithLegacyIntent(packageName)
        }

    private fun launchExplicitUri(packageName: String, rawUri: String): OpenAppLaunchAttempt {
        val uri = Uri.parse(rawUri)
        if (uri.scheme.isNullOrBlank()) {
            return OpenAppLaunchAttempt(
                status = OpenAppLaunchStatus.INVALID_URI,
                adapter = "explicit_uri",
                detail = "open_app URI requires a non-empty scheme",
            )
        }
        val intent = Intent(Intent.ACTION_VIEW, uri)
            .setPackage(packageName)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return startActivity(intent, adapter = "explicit_uri")
    }

    private fun launchWithLegacyIntent(packageName: String): OpenAppLaunchAttempt {
        val intent = packageManager.getLaunchIntentForPackage(packageName)
            ?: return OpenAppLaunchAttempt(
                status = OpenAppLaunchStatus.TARGET_NOT_FOUND,
                adapter = "getLaunchIntentForPackage",
                detail = "target package has no visible front-door activity",
            )
        intent.addFlags(
            Intent.FLAG_ACTIVITY_NEW_TASK or
                Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED,
        )
        return startActivity(intent, adapter = "getLaunchIntentForPackage")
    }

    private fun startActivity(intent: Intent, adapter: String): OpenAppLaunchAttempt = try {
        applicationContext.startActivity(intent)
        OpenAppLaunchAttempt(
            status = OpenAppLaunchStatus.ACCEPTED,
            adapter = adapter,
            detail = "Android accepted the activity launch request",
        )
    } catch (error: ActivityNotFoundException) {
        OpenAppLaunchAttempt(
            status = OpenAppLaunchStatus.TARGET_NOT_FOUND,
            adapter = adapter,
            detail = error.message.orEmpty().ifBlank { "target activity was not found" },
        )
    } catch (error: SecurityException) {
        OpenAppLaunchAttempt(
            status = OpenAppLaunchStatus.REJECTED,
            adapter = adapter,
            detail = error.message.orEmpty().ifBlank { "Android rejected the activity launch" },
        )
    }

    private fun launchWithIntentSender(packageName: String): OpenAppLaunchAttempt {
        val sender = packageManager.getLaunchIntentSenderForPackage(packageName)
        return try {
            applicationContext.startIntentSender(
                sender,
                null,
                0,
                0,
                0,
                backgroundActivityOptions(),
            )
            OpenAppLaunchAttempt(
                status = OpenAppLaunchStatus.ACCEPTED,
                adapter = "getLaunchIntentSenderForPackage",
                detail = "Android accepted the front-door IntentSender",
            )
        } catch (error: IntentSender.SendIntentException) {
            OpenAppLaunchAttempt(
                status = OpenAppLaunchStatus.TARGET_NOT_FOUND,
                adapter = "getLaunchIntentSenderForPackage",
                detail = error.message.orEmpty().ifBlank {
                    "target package is unknown or has no front-door activity"
                },
            )
        } catch (error: SecurityException) {
            OpenAppLaunchAttempt(
                status = OpenAppLaunchStatus.REJECTED,
                adapter = "getLaunchIntentSenderForPackage",
                detail = error.message.orEmpty().ifBlank {
                    "Android rejected the background front-door launch"
                },
            )
        }
    }

    @Suppress("DEPRECATION")
    private fun backgroundActivityOptions(): android.os.Bundle? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            return null
        }
        return ActivityOptions.makeBasic().apply {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                setPendingIntentBackgroundActivityStartMode(
                    ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED,
                )
            } else {
                setPendingIntentBackgroundActivityLaunchAllowed(true)
            }
        }.toBundle()
    }
}
