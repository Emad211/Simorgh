package ai.simorgh.android.transport

import java.io.Closeable
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit

fun interface ScheduledObservationTask {
    fun cancel()
}

interface ObservationScheduler : Closeable {
    fun nowMillis(): Long

    fun schedule(delayMillis: Long, task: () -> Unit): ScheduledObservationTask
}

class ExecutorObservationScheduler(
    private val executor: ScheduledExecutorService = Executors.newSingleThreadScheduledExecutor(),
) : ObservationScheduler {
    override fun nowMillis(): Long = System.nanoTime() / 1_000_000

    override fun schedule(delayMillis: Long, task: () -> Unit): ScheduledObservationTask {
        val future = executor.schedule(task, delayMillis.coerceAtLeast(0), TimeUnit.MILLISECONDS)
        return ScheduledObservationTask { future.cancel(false) }
    }

    override fun close() {
        executor.shutdownNow()
    }
}
