package ai.simorgh.android.device

enum class IntentSenderBackgroundGrant {
    LEGACY_BOOLEAN,
    ALLOWED,
    ALLOW_IF_VISIBLE,
    ALLOW_ALWAYS,
}

object BackgroundLaunchPolicy {
    const val BACKGROUND_ACTIVITY_RESTRICTION_SDK: Int = 29
    const val INTENT_SENDER_SDK: Int = 33
    const val EXPLICIT_MODE_SDK: Int = 34
    const val SPLIT_MODE_SDK: Int = 36

    fun requiresSpecialAccess(sdkInt: Int): Boolean {
        requireValidSdk(sdkInt)
        return sdkInt >= BACKGROUND_ACTIVITY_RESTRICTION_SDK
    }

    fun canLaunch(
        sdkInt: Int,
        appVisible: Boolean,
        overlayGranted: Boolean,
    ): Boolean =
        !requiresSpecialAccess(sdkInt) || appVisible || overlayGranted

    fun intentSenderGrant(
        sdkInt: Int,
        appVisible: Boolean,
    ): IntentSenderBackgroundGrant {
        requireValidSdk(sdkInt)
        require(sdkInt >= INTENT_SENDER_SDK) {
            "IntentSender launch adapter requires API $INTENT_SENDER_SDK or newer"
        }
        return when {
            sdkInt < EXPLICIT_MODE_SDK -> IntentSenderBackgroundGrant.LEGACY_BOOLEAN
            sdkInt < SPLIT_MODE_SDK -> IntentSenderBackgroundGrant.ALLOWED
            appVisible -> IntentSenderBackgroundGrant.ALLOW_IF_VISIBLE
            else -> IntentSenderBackgroundGrant.ALLOW_ALWAYS
        }
    }

    private fun requireValidSdk(sdkInt: Int) {
        require(sdkInt >= 1) { "sdkInt must be positive" }
    }
}
