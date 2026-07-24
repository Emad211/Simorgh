package ai.simorgh.android.accessibility

object AccessibilitySnapshotProjection {
    /**
     * Keep external-app evidence intact while reducing Simorgh's own UI to package presence only.
     *
     * This lets Core acknowledge the intentional transition into the Simorgh Activity without
     * transmitting connection fields or creating an observation/status feedback loop.
     */
    fun forDeviceTransport(
        snapshot: AccessibilitySnapshot,
        simorghPackageName: String,
    ): AccessibilitySnapshot {
        if (snapshot.activePackage != simorghPackageName) {
            return snapshot
        }
        return snapshot.copy(
            triggeringEventType = null,
            activeWindowId = null,
            rootNodeId = null,
            windows = emptyList(),
            nodes = emptyList(),
            truncated = false,
            truncationReasons = emptyList(),
            maxDepthObserved = 0,
        )
    }
}
