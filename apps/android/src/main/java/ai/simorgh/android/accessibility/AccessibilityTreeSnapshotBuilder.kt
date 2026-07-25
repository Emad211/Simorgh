package ai.simorgh.android.accessibility

import android.os.SystemClock
import java.security.MessageDigest
import java.util.ArrayDeque
import java.util.UUID
import kotlin.math.min

data class AccessibilitySnapshotLimits(
    val maxNodes: Int = 500,
    val maxDepth: Int = 40,
    val maxChildrenPerNode: Int = 100,
    val maxTextLength: Int = 512,
    val maxActionsPerNode: Int = 40,
) {
    init {
        require(maxNodes > 0)
        require(maxDepth >= 0)
        require(maxChildrenPerNode > 0)
        require(maxTextLength > 0)
        require(maxActionsPerNode > 0)
    }
}

class AccessibilityTreeSnapshotBuilder(
    private val limits: AccessibilitySnapshotLimits = AccessibilitySnapshotLimits(),
) {
    fun build(
        root: AccessibilityNodeReader?,
        windows: List<AccessibilityWindowSnapshot>,
        triggeringEventType: Int?,
        activePackageHint: String?,
        activeWindowIdHint: Int?,
        capturedAtMs: Long = System.currentTimeMillis(),
        capturedAtElapsedRealtimeMs: Long = SystemClock.elapsedRealtime(),
        snapshotId: String = UUID.randomUUID().toString(),
    ): AccessibilitySnapshot {
        if (root == null) {
            return AccessibilitySnapshot(
                snapshotId = snapshotId,
                capturedAtMs = capturedAtMs,
                capturedAtElapsedRealtimeMs = capturedAtElapsedRealtimeMs,
                triggeringEventType = triggeringEventType,
                activePackage = sanitize(activePackageHint),
                activeWindowId = activeWindowIdHint,
                windows = windows,
                nodes = emptyList(),
                truncated = false,
                truncationReasons = emptyList(),
                maxDepthObserved = 0,
            )
        }

        val pending = ArrayDeque<PendingNode>()
        val nodes = ArrayList<AccessibilityNodeSnapshot>(min(limits.maxNodes, 128))
        val truncationReasons = linkedSetOf<String>()
        var maxDepthObserved = 0
        var rootNodeId: String? = null
        var activePackage = sanitize(activePackageHint)
        var activeWindowId = activeWindowIdHint

        pending.addLast(
            PendingNode(
                reader = root,
                parentNodeId = null,
                path = "0",
                depth = 0,
            ),
        )

        try {
            while (pending.isNotEmpty()) {
                if (nodes.size >= limits.maxNodes) {
                    truncationReasons += REASON_NODE_LIMIT
                    break
                }

                val pendingNode = pending.removeLast()
                pendingNode.reader.use { reader ->
                    if (pendingNode.depth > limits.maxDepth) {
                        truncationReasons += REASON_DEPTH_LIMIT
                        return@use
                    }

                    val node = snapshotNode(reader, pendingNode)
                    nodes += node
                    if (rootNodeId == null) {
                        rootNodeId = node.nodeId
                        activePackage = node.packageName ?: activePackage
                        activeWindowId = node.windowId
                    }
                    maxDepthObserved = maxOf(maxDepthObserved, pendingNode.depth)

                    if (pendingNode.depth == limits.maxDepth) {
                        if (reader.childCount > 0) {
                            truncationReasons += REASON_DEPTH_LIMIT
                        }
                        return@use
                    }

                    val traversedChildCount = min(
                        reader.childCount.coerceAtLeast(0),
                        limits.maxChildrenPerNode,
                    )
                    if (reader.childCount > traversedChildCount) {
                        truncationReasons += REASON_CHILD_LIMIT
                    }

                    for (index in traversedChildCount - 1 downTo 0) {
                        val child = runCatching { reader.childAt(index) }.getOrNull() ?: continue
                        pending.addLast(
                            PendingNode(
                                reader = child,
                                parentNodeId = node.nodeId,
                                path = "${pendingNode.path}.$index",
                                depth = pendingNode.depth + 1,
                            ),
                        )
                    }
                }
            }
        } finally {
            while (pending.isNotEmpty()) {
                runCatching { pending.removeLast().reader.close() }
            }
        }

        return AccessibilitySnapshot(
            snapshotId = snapshotId,
            capturedAtMs = capturedAtMs,
            capturedAtElapsedRealtimeMs = capturedAtElapsedRealtimeMs,
            triggeringEventType = triggeringEventType,
            activePackage = activePackage,
            activeWindowId = activeWindowId,
            rootNodeId = rootNodeId,
            windows = windows,
            nodes = nodes,
            truncated = truncationReasons.isNotEmpty(),
            truncationReasons = truncationReasons.sorted(),
            maxDepthObserved = maxDepthObserved,
        )
    }

    private fun snapshotNode(
        reader: AccessibilityNodeReader,
        pendingNode: PendingNode,
    ): AccessibilityNodeSnapshot {
        val isPassword = reader.password
        val packageName = sanitize(reader.packageName)
        val className = sanitize(reader.className)
        val viewId = sanitize(reader.viewId)
        val text = if (isPassword) null else sanitize(reader.text)
        val contentDescription = if (isPassword) null else sanitize(reader.contentDescription)
        val hintText = if (isPassword) null else sanitize(reader.hintText)
        val stateDescription = if (isPassword) null else sanitize(reader.stateDescription)
        val nodeId = digest(
            listOf(
                reader.windowId.toString(),
                pendingNode.path,
                viewId.orEmpty(),
                className.orEmpty(),
            ).joinToString(separator = "|"),
        )
        val semanticFingerprint = digest(
            listOf(
                packageName.orEmpty(),
                viewId.orEmpty(),
                className.orEmpty(),
                text.orEmpty(),
                contentDescription.orEmpty(),
                hintText.orEmpty(),
                stateDescription.orEmpty(),
                reader.bounds.left.toString(),
                reader.bounds.top.toString(),
                reader.bounds.right.toString(),
                reader.bounds.bottom.toString(),
            ).joinToString(separator = "|"),
        )

        return AccessibilityNodeSnapshot(
            nodeId = nodeId,
            parentNodeId = pendingNode.parentNodeId,
            path = pendingNode.path,
            depth = pendingNode.depth,
            windowId = reader.windowId,
            packageName = packageName,
            className = className,
            viewId = viewId,
            text = text,
            contentDescription = contentDescription,
            hintText = hintText,
            stateDescription = stateDescription,
            bounds = reader.bounds,
            semanticFingerprint = semanticFingerprint,
            childCount = reader.childCount.coerceAtLeast(0),
            inputType = reader.inputType,
            clickable = reader.clickable,
            longClickable = reader.longClickable,
            focusable = reader.focusable,
            focused = reader.focused,
            editable = reader.editable,
            scrollable = reader.scrollable,
            enabled = reader.enabled,
            selected = reader.selected,
            checkable = reader.checkable,
            checked = reader.checked,
            visibleToUser = reader.visibleToUser,
            accessibilityFocused = reader.accessibilityFocused,
            password = isPassword,
            heading = reader.heading,
            actions = reader.actions
                .take(limits.maxActionsPerNode)
                .map { action ->
                    AccessibilityActionSnapshot(
                        id = action.id,
                        label = sanitize(action.label),
                    )
                },
        )
    }

    private fun sanitize(value: String?): String? {
        if (value == null) {
            return null
        }
        val normalized = value
            .replace(WHITESPACE_REGEX, " ")
            .trim()
        if (normalized.isEmpty()) {
            return null
        }
        return normalized.take(limits.maxTextLength)
    }

    private fun digest(value: String): String {
        val bytes = MessageDigest.getInstance("SHA-256")
            .digest(value.toByteArray(Charsets.UTF_8))
        val result = CharArray(HASH_CHARACTERS)
        for (index in 0 until HASH_BYTES) {
            val unsigned = bytes[index].toInt() and 0xFF
            result[index * 2] = HEX[unsigned ushr 4]
            result[index * 2 + 1] = HEX[unsigned and 0x0F]
        }
        return String(result)
    }

    private data class PendingNode(
        val reader: AccessibilityNodeReader,
        val parentNodeId: String?,
        val path: String,
        val depth: Int,
    )

    private companion object {
        val WHITESPACE_REGEX = Regex("\\s+")
        const val REASON_NODE_LIMIT = "node_limit"
        const val REASON_DEPTH_LIMIT = "depth_limit"
        const val REASON_CHILD_LIMIT = "child_limit"
        const val HASH_BYTES = 12
        const val HASH_CHARACTERS = HASH_BYTES * 2
        val HEX = "0123456789abcdef".toCharArray()
    }
}
