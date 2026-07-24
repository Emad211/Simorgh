package ai.simorgh.android.device

import java.util.concurrent.atomic.AtomicInteger

object SimorghAppVisibility {
    private val startedActivities = AtomicInteger(0)

    fun onActivityStarted() {
        startedActivities.incrementAndGet()
    }

    fun onActivityStopped() {
        while (true) {
            val current = startedActivities.get()
            if (current == 0 || startedActivities.compareAndSet(current, current - 1)) {
                return
            }
        }
    }

    fun isVisible(): Boolean = startedActivities.get() > 0

    internal fun resetForTest() {
        startedActivities.set(0)
    }
}
