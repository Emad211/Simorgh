package ai.simorgh.android.accessibility

import java.io.Closeable
import java.util.concurrent.CopyOnWriteArraySet

data class AccessibilityObserverState(
    val serviceConnected: Boolean,
    val latestSnapshot: AccessibilitySnapshot? = null,
    val lastError: String? = null,
)

object AccessibilityObservationBus {
    private val listeners = CopyOnWriteArraySet<(AccessibilityObserverState) -> Unit>()

    @Volatile
    private var currentState = AccessibilityObserverState(serviceConnected = false)

    fun current(): AccessibilityObserverState = currentState

    fun publish(state: AccessibilityObserverState) {
        currentState = state
        listeners.forEach { listener -> listener(state) }
    }

    fun subscribe(listener: (AccessibilityObserverState) -> Unit): Closeable {
        listeners.add(listener)
        listener(currentState)
        return Closeable { listeners.remove(listener) }
    }

    internal fun clearForTest() {
        currentState = AccessibilityObserverState(serviceConnected = false)
        listeners.clear()
    }
}
