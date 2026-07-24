package ai.simorgh.android.accessibility

import android.graphics.Rect
import android.os.Build
import android.view.accessibility.AccessibilityNodeInfo

class AndroidAccessibilityNodeReader(
    private val node: AccessibilityNodeInfo,
) : AccessibilityNodeReader {
    override val windowId: Int
        get() = node.windowId
    override val packageName: String?
        get() = node.packageName?.toString()
    override val className: String?
        get() = node.className?.toString()
    override val viewId: String?
        get() = node.viewIdResourceName
    override val text: String?
        get() = node.text?.toString()
    override val contentDescription: String?
        get() = node.contentDescription?.toString()
    override val hintText: String?
        get() = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            node.hintText?.toString()
        } else {
            null
        }
    override val stateDescription: String?
        get() = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            node.stateDescription?.toString()
        } else {
            null
        }
    override val bounds: ScreenBounds
        get() {
            val bounds = Rect()
            node.getBoundsInScreen(bounds)
            return ScreenBounds(
                left = bounds.left,
                top = bounds.top,
                right = bounds.right,
                bottom = bounds.bottom,
            )
        }
    override val childCount: Int
        get() = node.childCount
    override val inputType: Int
        get() = node.inputType
    override val clickable: Boolean
        get() = node.isClickable
    override val longClickable: Boolean
        get() = node.isLongClickable
    override val focusable: Boolean
        get() = node.isFocusable
    override val focused: Boolean
        get() = node.isFocused
    override val editable: Boolean
        get() = node.isEditable
    override val scrollable: Boolean
        get() = node.isScrollable
    override val enabled: Boolean
        get() = node.isEnabled
    override val selected: Boolean
        get() = node.isSelected
    override val checkable: Boolean
        get() = node.isCheckable
    @Suppress("DEPRECATION")
    override val checked: Boolean
        get() = node.isChecked
    override val visibleToUser: Boolean
        get() = node.isVisibleToUser
    override val accessibilityFocused: Boolean
        get() = node.isAccessibilityFocused
    override val password: Boolean
        get() = node.isPassword
    override val heading: Boolean
        get() = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            node.isHeading
        } else {
            false
        }
    override val actions: List<RawAccessibilityAction>
        get() = node.actionList.map { action ->
            RawAccessibilityAction(
                id = action.id,
                label = action.label?.toString(),
            )
        }

    override fun childAt(index: Int): AccessibilityNodeReader? =
        node.getChild(index)?.let(::AndroidAccessibilityNodeReader)

    @Suppress("DEPRECATION")
    override fun close() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            node.recycle()
        }
    }
}
