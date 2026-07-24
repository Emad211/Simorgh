package ai.simorgh.android.transport

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ReconnectPolicyTest {
    @Test
    fun `delay doubles until it reaches the configured ceiling`() {
        val policy = ReconnectPolicy(baseDelayMillis = 1_000, maxDelayMillis = 30_000)

        assertEquals(1_000, policy.delayMillis(1))
        assertEquals(2_000, policy.delayMillis(2))
        assertEquals(4_000, policy.delayMillis(3))
        assertEquals(16_000, policy.delayMillis(5))
        assertEquals(30_000, policy.delayMillis(6))
        assertEquals(30_000, policy.delayMillis(100))
    }

    @Test
    fun `attempt numbering starts at one`() {
        val policy = ReconnectPolicy()

        assertThrows(IllegalArgumentException::class.java) {
            policy.delayMillis(0)
        }
    }
}
