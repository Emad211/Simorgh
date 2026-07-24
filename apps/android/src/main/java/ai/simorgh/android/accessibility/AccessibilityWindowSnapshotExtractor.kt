package ai.simorgh.android.accessibility

import android.graphics.Rect
import android.os.Build
import android.view.accessibility.AccessibilityWindowInfo

object AccessibilityWindowSnapshotExtractor {
    fun extract(windows: List<AccessibilityWindowInfo>): List<AccessibilityWindowSnapshot> =
        windows.mapNotNull { window ->
            try {
                val bounds = Rect()
                window.getBoundsInScreen(bounds)
                AccessibilityWindowSnapshot(
                    id = window.id,
                    type = window.type,
                    layer = window.layer,
                    active = window.isActive,
                    focused = window.isFocused,
                    accessibilityFocused = window.isAccessibilityFocused,
                    title = window.title?.toString()?.trim()?.takeIf(String::isNotEmpty)?.take(512),
                    bounds = ScreenBounds(
                        left = bounds.left,
                        top = bounds.top,
                        right = bounds.right,
                        bottom = bounds.bottom,
                    ),
                    displayId = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                        window.displayId
                    } else {
                        null
                    },
                )
            } catch (_: RuntimeException) {
                null
            } finally {
                recycleIfRequired(window)
            }
        }

    @Suppress("DEPRECATION")
    private fun recycleIfRequired(window: AccessibilityWindowInfo) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            window.recycle()
        }
    }
}
