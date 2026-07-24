package ai.simorgh.android.accessibility

import java.io.Closeable
import java.util.concurrent.atomic.AtomicReference

object AccessibilityCaptureController {
    private val requester = AtomicReference<(() -> Unit)?>(null)

    fun install(candidate: () -> Unit): Closeable {
        check(requester.compareAndSet(null, candidate)) {
            "an Accessibility capture requester is already installed"
        }
        return Closeable { requester.compareAndSet(candidate, null) }
    }

    fun requestCapture(): Boolean {
        val active = requester.get() ?: return false
        active()
        return true
    }

    internal fun clearForTest() {
        requester.set(null)
    }
}
