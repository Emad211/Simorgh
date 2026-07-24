package ai.simorgh.android.accessibility

import java.io.Closeable

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
    private val lock = Any()
    private val listeners =
        linkedSetOf<(AcknowledgedAccessibilityObservation?) -> Unit>()
    private var latest: AcknowledgedAccessibilityObservation? = null

    fun latest(): AcknowledgedAccessibilityObservation? =
        synchronized(lock) { latest }

    fun publish(observation: AcknowledgedAccessibilityObservation) {
        synchronized(lock) {
            latest = observation
            listeners.forEach { listener -> listener(observation) }
        }
    }

    /**
     * Invalidate executable evidence from the previous Core connection without breaking subscribers.
     */
    internal fun reset() {
        synchronized(lock) {
            latest = null
            listeners.forEach { listener -> listener(null) }
        }
    }

    fun subscribe(
        listener: (AcknowledgedAccessibilityObservation?) -> Unit,
    ): Closeable {
        synchronized(lock) {
            listeners.add(listener)
            listener(latest)
        }
        return Closeable {
            synchronized(lock) {
                listeners.remove(listener)
            }
        }
    }

    internal fun clearForTest() {
        synchronized(lock) {
            latest = null
            listeners.clear()
        }
    }
}
