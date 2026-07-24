package ai.simorgh.android.accessibility

import java.io.Closeable

data class RawAccessibilityAction(
    val id: Int,
    val label: String? = null,
)

interface AccessibilityNodeReader : Closeable {
    val windowId: Int
    val packageName: String?
    val className: String?
    val viewId: String?
    val text: String?
    val contentDescription: String?
    val hintText: String?
    val stateDescription: String?
    val bounds: ScreenBounds
    val childCount: Int
    val inputType: Int
    val clickable: Boolean
    val longClickable: Boolean
    val focusable: Boolean
    val focused: Boolean
    val editable: Boolean
    val scrollable: Boolean
    val enabled: Boolean
    val selected: Boolean
    val checkable: Boolean
    val checked: Boolean
    val visibleToUser: Boolean
    val accessibilityFocused: Boolean
    val password: Boolean
    val heading: Boolean
    val actions: List<RawAccessibilityAction>

    fun childAt(index: Int): AccessibilityNodeReader?
}
