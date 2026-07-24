package ai.simorgh.android.actions

import java.io.Closeable
import java.util.concurrent.atomic.AtomicReference

data class ReceivedAndroidAction(
    val commandEnvelopeId: String,
    val command: AndroidActionCommand,
)

fun interface AndroidActionCompletion {
    fun complete(result: AndroidActionResult)
}

interface AndroidActionHandler {
    /**
     * Start exactly one already validated command.
     *
     * Return false when the execution subsystem cannot accept the command. A true return means
     * the handler owns completion and must invoke [completion] once.
     */
    fun submit(
        request: ReceivedAndroidAction,
        completion: AndroidActionCompletion,
    ): Boolean

    /** Return true when an active matching command accepted cancellation. */
    fun cancel(commandId: String, actionId: String, reason: String): Boolean
}

object AndroidActionHandlerRegistry {
    private val handler = AtomicReference<AndroidActionHandler?>()

    fun install(candidate: AndroidActionHandler): Closeable {
        check(handler.compareAndSet(null, candidate)) {
            "an Android action handler is already installed"
        }
        return Closeable {
            handler.compareAndSet(candidate, null)
        }
    }

    fun current(): AndroidActionHandler? = handler.get()
}
