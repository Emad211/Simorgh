package ai.simorgh.android.accessibility

import java.security.MessageDigest

object AccessibilitySnapshotFingerprint {
    fun calculate(snapshot: AccessibilitySnapshot): String {
        val digest = CanonicalDigest("simorgh-accessibility-state-v1\n")
        digest.addString("schema_version", snapshot.schemaVersion)
        digest.addString("active_package", snapshot.activePackage)
        digest.addLong("active_window_id", snapshot.activeWindowId?.toLong())
        digest.addString("root_node_id", snapshot.rootNodeId)
        digest.addBoolean("truncated", snapshot.truncated)
        digest.addLong("max_depth_observed", snapshot.maxDepthObserved.toLong())

        val reasons = snapshot.truncationReasons.sorted()
        digest.addLong("truncation_reason_count", reasons.size.toLong())
        reasons.forEachIndexed { index, reason ->
            digest.addLong("truncation_reason_index", index.toLong())
            digest.addString("truncation_reason", reason)
        }

        val windows = snapshot.windows.sortedWith(compareBy({ it.id }, { it.layer }))
        digest.addLong("window_count", windows.size.toLong())
        windows.forEachIndexed { index, window ->
            digest.addLong("window_index", index.toLong())
            digest.addLong("window_id", window.id.toLong())
            digest.addLong("window_type", window.type.toLong())
            digest.addLong("window_layer", window.layer.toLong())
            digest.addBoolean("window_active", window.active)
            digest.addBoolean("window_focused", window.focused)
            digest.addBoolean("window_accessibility_focused", window.accessibilityFocused)
            digest.addString("window_title", window.title)
            digest.addLong("window_bounds_left", window.bounds.left.toLong())
            digest.addLong("window_bounds_top", window.bounds.top.toLong())
            digest.addLong("window_bounds_right", window.bounds.right.toLong())
            digest.addLong("window_bounds_bottom", window.bounds.bottom.toLong())
            digest.addLong("window_display_id", window.displayId?.toLong())
        }

        val nodes = snapshot.nodes.sortedBy(AccessibilityNodeSnapshot::path)
        digest.addLong("node_count", nodes.size.toLong())
        nodes.forEachIndexed { index, node ->
            digest.addLong("node_index", index.toLong())
            digest.addString("node_id", node.nodeId)
            digest.addString("node_parent_node_id", node.parentNodeId)
            digest.addString("node_path", node.path)
            digest.addLong("node_depth", node.depth.toLong())
            digest.addLong("node_window_id", node.windowId.toLong())
            digest.addString("node_package_name", node.packageName)
            digest.addString("node_class_name", node.className)
            digest.addString("node_view_id", node.viewId)
            digest.addString("node_text", node.text)
            digest.addString("node_content_description", node.contentDescription)
            digest.addString("node_hint_text", node.hintText)
            digest.addString("node_state_description", node.stateDescription)
            digest.addString("node_semantic_fingerprint", node.semanticFingerprint)
            digest.addLong("node_bounds_left", node.bounds.left.toLong())
            digest.addLong("node_bounds_top", node.bounds.top.toLong())
            digest.addLong("node_bounds_right", node.bounds.right.toLong())
            digest.addLong("node_bounds_bottom", node.bounds.bottom.toLong())
            digest.addLong("node_child_count", node.childCount.toLong())
            digest.addLong("node_input_type", node.inputType.toLong())
            digest.addBoolean("node_clickable", node.clickable)
            digest.addBoolean("node_long_clickable", node.longClickable)
            digest.addBoolean("node_focusable", node.focusable)
            digest.addBoolean("node_focused", node.focused)
            digest.addBoolean("node_editable", node.editable)
            digest.addBoolean("node_scrollable", node.scrollable)
            digest.addBoolean("node_enabled", node.enabled)
            digest.addBoolean("node_selected", node.selected)
            digest.addBoolean("node_checkable", node.checkable)
            digest.addBoolean("node_checked", node.checked)
            digest.addBoolean("node_visible_to_user", node.visibleToUser)
            digest.addBoolean("node_accessibility_focused", node.accessibilityFocused)
            digest.addBoolean("node_password", node.password)
            digest.addBoolean("node_heading", node.heading)

            val actions = node.actions.sortedWith(compareBy({ it.id }, { it.label.orEmpty() }))
            digest.addLong("node_action_count", actions.size.toLong())
            actions.forEachIndexed { actionIndex, action ->
                digest.addLong("action_index", actionIndex.toLong())
                digest.addLong("action_id", action.id.toLong())
                digest.addString("action_label", action.label)
            }
        }

        return digest.hexdigest()
    }

    private class CanonicalDigest(prefix: String) {
        private val digest = MessageDigest.getInstance("SHA-256").apply {
            update(prefix.toByteArray(Charsets.US_ASCII))
        }

        fun addString(name: String, value: String?) {
            addName(name)
            if (value == null) {
                digest.update(NULL_TOKEN)
                return
            }
            val encoded = value.toByteArray(Charsets.UTF_8)
            digest.update(STRING_TOKEN)
            digest.update(encoded.size.toString().toByteArray(Charsets.US_ASCII))
            digest.update(COLON)
            digest.update(encoded)
            digest.update(TERMINATOR)
        }

        fun addLong(name: String, value: Long?) {
            addName(name)
            if (value == null) {
                digest.update(NULL_TOKEN)
                return
            }
            digest.update(INTEGER_TOKEN)
            digest.update(value.toString().toByteArray(Charsets.US_ASCII))
            digest.update(TERMINATOR)
        }

        fun addBoolean(name: String, value: Boolean) {
            addName(name)
            digest.update(if (value) TRUE_TOKEN else FALSE_TOKEN)
        }

        fun hexdigest(): String = digest.digest().joinToString(separator = "") { byte ->
            "%02x".format(byte.toInt() and 0xFF)
        }

        private fun addName(name: String) {
            digest.update(name.toByteArray(Charsets.US_ASCII))
            digest.update(EQUALS)
        }
    }

    private val NULL_TOKEN = "N;".toByteArray(Charsets.US_ASCII)
    private val STRING_TOKEN = "S".toByteArray(Charsets.US_ASCII)
    private val INTEGER_TOKEN = "I".toByteArray(Charsets.US_ASCII)
    private val TRUE_TOKEN = "B1;".toByteArray(Charsets.US_ASCII)
    private val FALSE_TOKEN = "B0;".toByteArray(Charsets.US_ASCII)
    private val COLON = ":".toByteArray(Charsets.US_ASCII)
    private val TERMINATOR = ";".toByteArray(Charsets.US_ASCII)
    private val EQUALS = "=".toByteArray(Charsets.US_ASCII)
}
