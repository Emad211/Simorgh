package ai.simorgh.android.accessibility

import java.io.Closeable
import java.util.concurrent.CopyOnWriteArraySet

data class AcknowledgedAccessibilityObservation(
    val streamId: String,
    val sequence: Long,
    val stateFingerprint: String,
    val snapshotId: String,
    val capturedAtMs: Long,
    val activePackage: String? = null,
    val acknowledgedAtMs: Long,
) {
    constructor(
        streamId: String,
        sequence: Long,
        stateFingerprint: String,
        snapshot: AccessibilitySnapshot,
        acknowledgedAtMs: Long,
    ) : this(
        streamId = streamId,
        sequence = sequence,
        stateFingerprint = stateFingerprint,
        snapshotId = snapshot.snapshotId,
        capturedAtMs = snapshot.capturedAtMs,
        activePackage = snapshot.activePackage,
        acknowledgedAtMs = acknowledgedAtMs,
    )
}

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

    internal fun reset() {
        latest = null
        listeners.clear()
    }

    internal fun clearForTest() = reset()
}
