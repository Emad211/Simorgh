package ai.simorgh.android.service

import ai.simorgh.android.transport.ConnectionPhase
import ai.simorgh.android.transport.ConnectionState
import org.junit.Assert.assertEquals
import org.junit.Test

class ConnectionStatusBusTest {
    @Test
    fun `subscriber receives current and future service snapshots`() {
        val initial = ConnectionStatusBus.current()
        val observed = mutableListOf<ServiceConnectionSnapshot>()
        val subscription = ConnectionStatusBus.subscribe(observed::add)

        val connected = ServiceConnectionSnapshot(
            serviceRunning = true,
            connectionState = ConnectionState(ConnectionPhase.CONNECTED),
            lastProtocolEvent = "registered",
        )
        ConnectionStatusBus.publish(connected)

        subscription.close()
        ConnectionStatusBus.publish(
            ServiceConnectionSnapshot(
                serviceRunning = false,
                connectionState = ConnectionState.Disconnected,
            ),
        )

        assertEquals(initial, observed.first())
        assertEquals(connected, observed.last())
        assertEquals(2, observed.size)
    }
}
