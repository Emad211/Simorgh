package ai.simorgh.android.device

import android.os.Build
import ai.simorgh.android.BuildConfig
import ai.simorgh.android.protocol.ObservationRefreshProtocol
import ai.simorgh.android.protocol.ProtocolVersion

data class DeviceCapabilities(
    val protocolVersion: String,
    val appVersion: String,
    val sdkInt: Int,
    val androidRelease: String,
    val manufacturer: String,
    val model: String,
    val buildFingerprint: String,
    val supportTier: AndroidSupportTier,
    val capabilities: Set<String>,
) {
    companion object {
        fun current(): DeviceCapabilities {
            val compatibility = AndroidCompatibility.profileFor(Build.VERSION.SDK_INT)
            val capabilities = buildSet {
                add("device.identity")
                add("device.network_state")
                add("device.action_transport.v1")
                add("android.action.contract.v1")
                add("android.open_app.execution.v1")
                add(ObservationRefreshProtocol.CAPABILITY)
                if (BackgroundLaunchAccess.requiresSpecialAccess()) {
                    add("android.open_app.background_launch.requires_visible_or_overlay_access")
                } else {
                    add("android.open_app.background_launch.legacy_allowed")
                }
                add("android.launcher_surface")
                add("android.accessibility.observe.platform")

                if (compatibility.canDispatchGestures) {
                    add("android.accessibility.gesture.platform")
                }
                if (compatibility.canTakeAccessibilityScreenshot) {
                    add("android.screen.capture.accessibility.platform")
                }
            }

            return DeviceCapabilities(
                protocolVersion = ProtocolVersion.CURRENT,
                appVersion = BuildConfig.VERSION_NAME,
                sdkInt = Build.VERSION.SDK_INT,
                androidRelease = Build.VERSION.RELEASE,
                manufacturer = Build.MANUFACTURER.orEmpty(),
                model = Build.MODEL.orEmpty(),
                buildFingerprint = Build.FINGERPRINT.orEmpty(),
                supportTier = compatibility.tier,
                capabilities = capabilities,
            )
        }
    }
}
