package ai.simorgh.android.device

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BackgroundLaunchPolicyTest {
    @Test
    fun `Android 7 and Android 9 do not require overlay access`() {
        listOf(24, 28).forEach { sdkInt ->
            assertFalse(BackgroundLaunchPolicy.requiresSpecialAccess(sdkInt))
            assertTrue(
                BackgroundLaunchPolicy.canLaunch(
                    sdkInt = sdkInt,
                    appVisible = false,
                    overlayGranted = false,
                ),
            )
        }
    }

    @Test
    fun `Android 10 and current Android block an invisible app without overlay`() {
        listOf(29, 36).forEach { sdkInt ->
            assertTrue(BackgroundLaunchPolicy.requiresSpecialAccess(sdkInt))
            assertFalse(
                BackgroundLaunchPolicy.canLaunch(
                    sdkInt = sdkInt,
                    appVisible = false,
                    overlayGranted = false,
                ),
            )
        }
    }

    @Test
    fun `visible Simorgh or overlay access satisfies modern launch prerequisite`() {
        assertTrue(
            BackgroundLaunchPolicy.canLaunch(
                sdkInt = 29,
                appVisible = true,
                overlayGranted = false,
            ),
        )
        assertTrue(
            BackgroundLaunchPolicy.canLaunch(
                sdkInt = 36,
                appVisible = false,
                overlayGranted = true,
            ),
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun `invalid SDK input fails closed`() {
        BackgroundLaunchPolicy.requiresSpecialAccess(0)
    }
}
