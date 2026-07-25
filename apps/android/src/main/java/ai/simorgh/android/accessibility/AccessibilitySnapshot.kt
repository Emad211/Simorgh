package ai.simorgh.android.accessibility

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.Transient

@Serializable
data class ScreenBounds(
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int,
) {
    val width: Int
        get() = (right - left).coerceAtLeast(0)

    val height: Int
        get() = (bottom - top).coerceAtLeast(0)
}

@Serializable
data class AccessibilityActionSnapshot(
    val id: Int,
    val label: String? = null,
)

@Serializable
data class AccessibilityNodeSnapshot(
    @SerialName("node_id")
    val nodeId: String,
    @SerialName("parent_node_id")
    val parentNodeId: String? = null,
    val path: String,
    val depth: Int,
    @SerialName("window_id")
    val windowId: Int,
    @SerialName("package_name")
    val packageName: String? = null,
    @SerialName("class_name")
    val className: String? = null,
    @SerialName("view_id")
    val viewId: String? = null,
    val text: String? = null,
    @SerialName("content_description")
    val contentDescription: String? = null,
    @SerialName("hint_text")
    val hintText: String? = null,
    @SerialName("state_description")
    val stateDescription: String? = null,
    val bounds: ScreenBounds,
    @SerialName("semantic_fingerprint")
    val semanticFingerprint: String,
    @SerialName("child_count")
    val childCount: Int,
    @SerialName("input_type")
    val inputType: Int,
    val clickable: Boolean,
    @SerialName("long_clickable")
    val longClickable: Boolean,
    val focusable: Boolean,
    val focused: Boolean,
    val editable: Boolean,
    val scrollable: Boolean,
    val enabled: Boolean,
    val selected: Boolean,
    val checkable: Boolean,
    val checked: Boolean,
    @SerialName("visible_to_user")
    val visibleToUser: Boolean,
    @SerialName("accessibility_focused")
    val accessibilityFocused: Boolean,
    val password: Boolean,
    val heading: Boolean,
    val actions: List<AccessibilityActionSnapshot>,
)

@Serializable
data class AccessibilityWindowSnapshot(
    val id: Int,
    val type: Int,
    val layer: Int,
    val active: Boolean,
    val focused: Boolean,
    @SerialName("accessibility_focused")
    val accessibilityFocused: Boolean,
    val title: String? = null,
    val bounds: ScreenBounds,
    @SerialName("display_id")
    val displayId: Int? = null,
)

@Serializable
data class AccessibilitySnapshot(
    @SerialName("schema_version")
    val schemaVersion: String = SCHEMA_VERSION,
    @SerialName("snapshot_id")
    val snapshotId: String,
    @SerialName("captured_at_ms")
    val capturedAtMs: Long,
    /**
     * Local-only monotonic capture time. It is deliberately excluded from serialization and
     * canonical state fingerprints so the wire contract remains schema 1.0.
     *
     * The default preserves deterministic JVM fixtures whose wall and monotonic test clocks use
     * one synthetic scale. Production builders always pass `SystemClock.elapsedRealtime()`.
     */
    @Transient
    val capturedAtElapsedRealtimeMs: Long = capturedAtMs,
    @SerialName("triggering_event_type")
    val triggeringEventType: Int? = null,
    @SerialName("active_package")
    val activePackage: String? = null,
    @SerialName("active_window_id")
    val activeWindowId: Int? = null,
    @SerialName("root_node_id")
    val rootNodeId: String? = null,
    val windows: List<AccessibilityWindowSnapshot>,
    val nodes: List<AccessibilityNodeSnapshot>,
    val truncated: Boolean,
    @SerialName("truncation_reasons")
    val truncationReasons: List<String>,
    @SerialName("max_depth_observed")
    val maxDepthObserved: Int,
) {
    companion object {
        const val SCHEMA_VERSION: String = "1.0"
    }
}
