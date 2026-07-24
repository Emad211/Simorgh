package ai.simorgh.android.service

import ai.simorgh.android.transport.ConnectionState
import java.io.Closeable
import java.util.concurrent.CopyOnWriteArraySet

data class ServiceConnectionSnapshot(
    val serviceRunning: Boolean,
    val connectionState: ConnectionState,
    val lastProtocolEvent: String? = null,
)

object ConnectionStatusBus {
    private val listeners = CopyOnWriteArraySet<(ServiceConnectionSnapshot) -> Unit>()

    @Volatile
    private var currentSnapshot = ServiceConnectionSnapshot(
        serviceRunning = false,
        connectionState = ConnectionState.Disconnected,
    )

    fun current(): ServiceConnectionSnapshot = currentSnapshot

    fun publish(snapshot: ServiceConnectionSnapshot) {
        currentSnapshot = snapshot
        listeners.forEach { listener -> listener(snapshot) }
    }

    fun subscribe(listener: (ServiceConnectionSnapshot) -> Unit): Closeable {
        listeners.add(listener)
        listener(currentSnapshot)
        return Closeable { listeners.remove(listener) }
    }
}
