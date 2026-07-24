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
    val capabilities: Set<String>,
) {
    companion object {
        fun current(): DeviceCapabilities = DeviceCapabilities(
            protocolVersion = ProtocolVersion.CURRENT,
            appVersion = BuildConfig.VERSION_NAME,
            sdkInt = Build.VERSION.SDK_INT,
            androidRelease = Build.VERSION.RELEASE,
            manufacturer = Build.MANUFACTURER.orEmpty(),
            model = Build.MODEL.orEmpty(),
            capabilities = setOf(
                "device.identity",
                "device.network_state",
                "android.launcher_surface",
            ),
        )
    }
}
