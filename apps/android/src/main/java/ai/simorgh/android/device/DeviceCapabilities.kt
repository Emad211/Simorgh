package ai.simorgh.android.device

import android.os.Build
import ai.simorgh.android.BuildConfig
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
                add("android.launcher_surface")
                add("android.accessibility.observe.platform")
                add("android.accessibility.node_action.platform")

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
