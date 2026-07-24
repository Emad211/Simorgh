package ai.simorgh.android.device

enum class AndroidSupportTier {
    UNSUPPORTED,
    COMPATIBLE,
    ENHANCED,
    FULL,
    FULL_CURRENT,
    EXPERIMENTAL,
}

data class AndroidCompatibilityProfile(
    val sdkInt: Int,
    val tier: AndroidSupportTier,
    val canDispatchGestures: Boolean,
    val canTakeAccessibilityScreenshot: Boolean,
)

object AndroidCompatibility {
    const val MIN_SUPPORTED_SDK: Int = 24
    const val CURRENT_STABLE_SDK: Int = 36

    fun profileFor(sdkInt: Int): AndroidCompatibilityProfile = AndroidCompatibilityProfile(
        sdkInt = sdkInt,
        tier = when {
            sdkInt < MIN_SUPPORTED_SDK -> AndroidSupportTier.UNSUPPORTED
            sdkInt <= 27 -> AndroidSupportTier.COMPATIBLE
            sdkInt <= 29 -> AndroidSupportTier.ENHANCED
            sdkInt <= 32 -> AndroidSupportTier.FULL
            sdkInt <= CURRENT_STABLE_SDK -> AndroidSupportTier.FULL_CURRENT
            else -> AndroidSupportTier.EXPERIMENTAL
        },
        canDispatchGestures = sdkInt >= 24,
        canTakeAccessibilityScreenshot = sdkInt >= 30,
    )
}
