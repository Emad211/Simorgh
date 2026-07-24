package ai.simorgh.android.transport

enum class ConnectionPhase {
    DISCONNECTED,
    CONNECTING,
    REGISTERING,
    CONNECTED,
    RETRY_WAIT,
    FAILED,
}

data class ConnectionState(
    val phase: ConnectionPhase,
    val detail: String? = null,
    val reconnectAttempt: Int = 0,
) {
    companion object {
        val Disconnected: ConnectionState = ConnectionState(ConnectionPhase.DISCONNECTED)
    }
}
