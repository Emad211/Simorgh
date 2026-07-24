package ai.simorgh.android.accessibility

import java.io.Closeable
import java.util.concurrent.CopyOnWriteArraySet

data class AcknowledgedAccessibilityObservation(
    val streamId: String,
    val sequence: Long,
    val stateFingerprint: String,
    val snapshot: AccessibilitySnapshot,
    val acknowledgedAtMs: Long,
)

object AccessibilityAcknowledgementBus {
    private val listeners =
        CopyOnWriteArraySet<(AcknowledgedAccessibilityObservation) -> Unit>()

    @Volatile
    private var latest: AcknowledgedAccessibilityObservation? = null

    fun latest(): AcknowledgedAccessibilityObservation? = latest

    fun publish(observation: AcknowledgedAccessibilityObservation) {
        latest = observation
        listeners.forEach { listener -> listener(observation) }
    }

    fun subscribe(listener: (AcknowledgedAccessibilityObservation) -> Unit): Closeable {
        listeners.add(listener)
        latest?.let(listener)
        return Closeable { listeners.remove(listener) }
    }

    internal fun clearForTest() {
        latest = null
        listeners.clear()
    }
}
