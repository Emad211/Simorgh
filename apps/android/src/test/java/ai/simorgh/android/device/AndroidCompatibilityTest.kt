package ai.simorgh.android.device

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidCompatibilityTest {
    @Test
    fun `api 24 is the minimum general operator tier`() {
        val profile = AndroidCompatibility.profileFor(sdkInt = 24)

        assertTrue(profile.canDispatchGestures)
        assertFalse(profile.canTakeAccessibilityScreenshot)
        assertEquals(AndroidSupportTier.COMPATIBLE, profile.tier)
    }

    @Test
    fun `api 30 enables the full screenshot tier`() {
        val profile = AndroidCompatibility.profileFor(sdkInt = 30)

        assertTrue(profile.canDispatchGestures)
        assertTrue(profile.canTakeAccessibilityScreenshot)
        assertEquals(AndroidSupportTier.FULL, profile.tier)
    }

    @Test
    fun `api below minimum is unsupported`() {
        val profile = AndroidCompatibility.profileFor(sdkInt = 23)

        assertFalse(profile.canDispatchGestures)
        assertEquals(AndroidSupportTier.UNSUPPORTED, profile.tier)
    }
}
