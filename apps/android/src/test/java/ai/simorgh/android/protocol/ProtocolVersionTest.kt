package ai.simorgh.android.protocol

import org.junit.Assert.assertEquals
import org.junit.Test

class ProtocolVersionTest {
    @Test
    fun currentProtocolVersionIsStable() {
        assertEquals("1.0", ProtocolVersion.CURRENT)
    }
}
