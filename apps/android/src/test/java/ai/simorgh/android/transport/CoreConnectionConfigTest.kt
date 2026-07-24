package ai.simorgh.android.transport

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class CoreConnectionConfigTest {
    @Test
    fun `valid WebSocket endpoint is normalized`() {
        val config = CoreConnectionConfig(
            endpoint = "  wss://simorgh.example/v1/devices/ws  ",
            deviceToken = "  secret-token  ",
        ).validated()

        assertEquals("wss://simorgh.example/v1/devices/ws", config.endpoint)
        assertEquals("secret-token", config.deviceToken)
    }

    @Test
    fun `http endpoint is rejected`() {
        assertThrows(IllegalArgumentException::class.java) {
            CoreConnectionConfig(
                endpoint = "https://simorgh.example/v1/devices/ws",
                deviceToken = "secret-token",
            ).validated()
        }
    }

    @Test
    fun `embedded endpoint credentials are rejected`() {
        assertThrows(IllegalArgumentException::class.java) {
            CoreConnectionConfig(
                endpoint = "wss://user:password@simorgh.example/v1/devices/ws",
                deviceToken = "secret-token",
            ).validated()
        }
    }

    @Test
    fun `blank device token is rejected`() {
        assertThrows(IllegalArgumentException::class.java) {
            CoreConnectionConfig(
                endpoint = "wss://simorgh.example/v1/devices/ws",
                deviceToken = "   ",
            ).validated()
        }
    }
}
