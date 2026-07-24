package ai.simorgh.android.accessibility

import java.security.MessageDigest

object AccessibilitySnapshotFingerprint {
    fun calculate(snapshot: AccessibilitySnapshot): String {
        val digest = MessageDigest.getInstance("SHA-256")

        fun update(value: Any?) {
            digest.update(value?.toString().orEmpty().toByteArray(Charsets.UTF_8))
            digest.update(SEPARATOR)
        }

        update(snapshot.schemaVersion)
        update(snapshot.activePackage)
        update(snapshot.activeWindowId)
        update(snapshot.rootNodeId)
        update(snapshot.truncated)
        snapshot.truncationReasons.sorted().forEach(::update)

        snapshot.windows
            .sortedWith(compareBy({ it.id }, { it.layer }))
            .forEach { window ->
                update(window.id)
                update(window.type)
                update(window.layer)
                update(window.active)
                update(window.focused)
                update(window.accessibilityFocused)
                update(window.title)
                update(window.bounds.left)
                update(window.bounds.top)
                update(window.bounds.right)
                update(window.bounds.bottom)
                update(window.displayId)
            }

        snapshot.nodes.forEach { node ->
            update(node.path)
            update(node.semanticFingerprint)
            update(node.childCount)
            update(node.clickable)
            update(node.longClickable)
            update(node.focusable)
            update(node.focused)
            update(node.editable)
            update(node.scrollable)
            update(node.enabled)
            update(node.selected)
            update(node.checkable)
            update(node.checked)
            update(node.visibleToUser)
            update(node.accessibilityFocused)
            update(node.password)
            update(node.heading)
            node.actions.forEach { action ->
                update(action.id)
                update(action.label)
            }
        }

        return digest.digest().joinToString(separator = "") { byte ->
            "%02x".format(byte.toInt() and 0xFF)
        }
    }

    private val SEPARATOR = byteArrayOf(0)
}
