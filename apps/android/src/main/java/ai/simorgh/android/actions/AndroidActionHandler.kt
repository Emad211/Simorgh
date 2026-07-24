package ai.simorgh.android.actions

import java.io.Closeable
import java.util.concurrent.atomic.AtomicBoolean
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
     * Return false only when the execution subsystem did not begin the command and cannot accept
     * ownership. A true return means the handler owns completion and must invoke [completion] once.
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
        val guarded = ExceptionShieldingActionHandler(candidate)
        check(handler.compareAndSet(null, guarded)) {
            "an Android action handler is already installed"
        }
        return Closeable {
            handler.compareAndSet(guarded, null)
        }
    }

    fun current(): AndroidActionHandler? = handler.get()

    private class ExceptionShieldingActionHandler(
        private val delegate: AndroidActionHandler,
        private val nowMillis: () -> Long = System::currentTimeMillis,
    ) : AndroidActionHandler {
        override fun submit(
            request: ReceivedAndroidAction,
            completion: AndroidActionCompletion,
        ): Boolean {
            val startedAtMs = nowMillis()
            val completionCalled = AtomicBoolean(false)
            val guardedCompletion = AndroidActionCompletion { result ->
                check(completionCalled.compareAndSet(false, true)) {
                    "Android action handler completed more than once"
                }
                completion.complete(result)
            }

            return try {
                delegate.submit(request, guardedCompletion)
            } catch (error: Exception) {
                if (completionCalled.get()) {
                    throw error
                }
                val finishedAtMs = maxOf(startedAtMs, nowMillis())
                completion.complete(
                    AndroidActionContractValidator.validate(
                        AndroidActionResult(
                            commandId = request.command.commandId,
                            actionId = request.command.actionId,
                            outcome = ActionOutcome.BLOCKED,
                            failureCode = ActionFailureCode.INTERNAL_ERROR,
                            startedAtMs = startedAtMs,
                            finishedAtMs = finishedAtMs,
                            attempts = 0,
                            detail = (
                                "Android action handler threw ${error.javaClass.simpleName}; " +
                                    "execution state is uncertain and the command will not be replayed"
                                ).take(MAX_DETAIL_LENGTH),
                        ),
                    ),
                )
                true
            }
        }

        override fun cancel(commandId: String, actionId: String, reason: String): Boolean =
            runCatching { delegate.cancel(commandId, actionId, reason) }.getOrDefault(false)
    }

    private const val MAX_DETAIL_LENGTH = 2_000
}
