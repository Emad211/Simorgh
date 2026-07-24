package ai.simorgh.android.accessibility

import android.accessibilityservice.AccessibilityService
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent

class SimorghAccessibilityService : AccessibilityService() {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val snapshotBuilder = AccessibilityTreeSnapshotBuilder()

    private var latestEventType: Int? = null
    private var latestPackageName: String? = null
    private var latestWindowId: Int? = null
    private var serviceConnected = false

    private val captureRunnable = Runnable(::captureSnapshot)

    override fun onServiceConnected() {
        super.onServiceConnected()
        serviceConnected = true
        AccessibilityObservationBus.publish(
            AccessibilityObserverState(serviceConnected = true),
        )
        scheduleCapture(immediate = true)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) {
            return
        }
        latestEventType = event.eventType
        latestPackageName = event.packageName?.toString()
        latestWindowId = event.windowId.takeIf { it >= 0 }
        scheduleCapture(immediate = false)
    }

    override fun onInterrupt() {
        val current = AccessibilityObservationBus.current()
        AccessibilityObservationBus.publish(
            current.copy(lastError = "accessibility_service_interrupted"),
        )
    }

    override fun onDestroy() {
        serviceConnected = false
        mainHandler.removeCallbacks(captureRunnable)
        AccessibilityObservationBus.publish(
            AccessibilityObserverState(serviceConnected = false),
        )
        super.onDestroy()
    }

    private fun scheduleCapture(immediate: Boolean) {
        mainHandler.removeCallbacks(captureRunnable)
        if (immediate) {
            mainHandler.post(captureRunnable)
        } else {
            mainHandler.postDelayed(captureRunnable, CAPTURE_DEBOUNCE_MILLIS)
        }
    }

    private fun captureSnapshot() {
        if (!serviceConnected) {
            return
        }

        try {
            val windowSnapshots = AccessibilityWindowSnapshotExtractor.extract(windows.orEmpty())
            val root = rootInActiveWindow?.let(::AndroidAccessibilityNodeReader)
            val snapshot = snapshotBuilder.build(
                root = root,
                windows = windowSnapshots,
                triggeringEventType = latestEventType,
                activePackageHint = latestPackageName,
                activeWindowIdHint = latestWindowId,
            )
            AccessibilityObservationBus.publish(
                AccessibilityObserverState(
                    serviceConnected = true,
                    latestSnapshot = snapshot,
                ),
            )
        } catch (error: RuntimeException) {
            val current = AccessibilityObservationBus.current()
            AccessibilityObservationBus.publish(
                current.copy(
                    serviceConnected = true,
                    lastError = error.javaClass.simpleName,
                ),
            )
        }
    }

    private companion object {
        const val CAPTURE_DEBOUNCE_MILLIS = 150L
    }
}
