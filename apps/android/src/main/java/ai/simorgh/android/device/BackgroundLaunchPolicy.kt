package ai.simorgh.android.device

object BackgroundLaunchPolicy {
    const val BACKGROUND_ACTIVITY_RESTRICTION_SDK: Int = 29

    fun requiresSpecialAccess(sdkInt: Int): Boolean {
        require(sdkInt >= 1) { "sdkInt must be positive" }
        return sdkInt >= BACKGROUND_ACTIVITY_RESTRICTION_SDK
    }

    fun canLaunch(
        sdkInt: Int,
        appVisible: Boolean,
        overlayGranted: Boolean,
    ): Boolean =
        !requiresSpecialAccess(sdkInt) || appVisible || overlayGranted
}
