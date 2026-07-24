package ai.simorgh.android.accessibility

import java.io.Closeable
import java.util.concurrent.CopyOnWriteArraySet

data class AcknowledgedSnapshotReference(
    val snapshotId: String,
    val capturedAtMs: Long,
    val activePackage: String? = null,
)

data class AcknowledgedAccessibilityObservation(
    val streamId: String,
    val sequence: Long,
    val stateFingerprint: String,
    val snapshotId: String,
    val capturedAtMs: Long,
    val activePackage: String? = null,
    val acknowledgedAtMs: Long,
) {
    val snapshot: AcknowledgedSnapshotReference
        get() = AcknowledgedSnapshotReference(
            snapshotId = snapshotId,
            capturedAtMs = capturedAtMs,
            activePackage = activePackage,
        )

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
        CopyOnWriteArraySet<(AcknowledgedAccessibilityObservation?) -> Unit>()

    @Volatile
    private var latest: AcknowledgedAccessibilityObservation? = null

    fun latest(): AcknowledgedAccessibilityObservation? = latest

    fun publish(observation: AcknowledgedAccessibilityObservation) {
        latest = observation
        listeners.forEach { listener -> listener(observation) }
    }

    /**
     * Invalidate executable evidence from the previous Core connection without breaking subscribers.
     */
    internal fun reset() {
        latest = null
        listeners.forEach { listener -> listener(null) }
    }

    fun subscribe(
        listener: (AcknowledgedAccessibilityObservation?) -> Unit,
    ): Closeable {
        listeners.add(listener)
        listener(latest)
        return Closeable { listeners.remove(listener) }
    }

    internal fun clearForTest() {
        latest = null
        listeners.clear()
    }
}
