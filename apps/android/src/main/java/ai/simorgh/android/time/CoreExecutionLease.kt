package ai.simorgh.android.time

import kotlin.math.min

enum class CoreExecutionClockFailureKind {
    CLOCK_UNAVAILABLE,
    CLOCK_GENERATION_CHANGED,
    ISSUED_AT_IN_FUTURE,
    UNCERTAINTY,
    EXPIRED,
}

sealed interface CoreExecutionLeaseStart {
    data class Available(val lease: CoreExecutionLease) : CoreExecutionLeaseStart

    data class Unavailable(
        val kind: CoreExecutionClockFailureKind,
        val detail: String,
        val fallbackCoreTimeMs: Long,
        val reading: CoreClockReading? = null,
    ) : CoreExecutionLeaseStart
}

sealed interface CoreExecutionBudget {
    data class Available(
        val milliseconds: Long,
        val reading: CoreClockReading,
    ) : CoreExecutionBudget

    data class Unavailable(
        val kind: CoreExecutionClockFailureKind,
        val detail: String,
        val reading: CoreClockReading? = null,
    ) : CoreExecutionBudget
}

/**
 * One action-scoped mapping between elapsedRealtime and Core epoch time.
 *
 * The initial conservative deadline is never extended. Later heartbeat samples can narrow the
 * budget, invalidate it, or reveal a new connection generation, but can never make the action run
 * longer than the budget accepted at the beginning.
 */
class CoreExecutionLease internal constructor(
    private val clock: CoreClock,
    val generation: Long,
    val startedAtElapsedRealtimeMs: Long,
    val startedAtCoreTimeMs: Long,
    val initialUncertaintyMs: Long,
    private val deadlineAtCoreTimeMs: Long,
    private val deadlineAtElapsedRealtimeMs: Long,
) {
    fun coreTimeNowMs(): Long {
        val nowElapsed = clock.elapsedRealtimeMs()
        val elapsed = (nowElapsed - startedAtElapsedRealtimeMs).coerceAtLeast(0)
        return saturatingAdd(startedAtCoreTimeMs, elapsed).coerceAtLeast(0)
    }

    /**
     * True only when evidence was captured after lease creation and strictly before the initial
     * conservative local deadline. ACK/network delay after capture does not invalidate it.
     */
    fun wasEvidenceCapturedBeforeDeadline(capturedAtElapsedRealtimeMs: Long): Boolean =
        capturedAtElapsedRealtimeMs >= startedAtElapsedRealtimeMs &&
            capturedAtElapsedRealtimeMs < deadlineAtElapsedRealtimeMs

    fun remainingBudget(requestedMilliseconds: Long): CoreExecutionBudget {
        if (requestedMilliseconds <= 0) {
            return CoreExecutionBudget.Unavailable(
                kind = CoreExecutionClockFailureKind.EXPIRED,
                detail = "requested execution budget is not positive",
            )
        }
        val current = clock.deadlineBudget(deadlineAtCoreTimeMs)
        if (current is CoreDeadlineBudget.Unavailable) {
            return current.toExecutionBudget()
        }
        current as CoreDeadlineBudget.Available
        if (current.reading.generation != generation) {
            return CoreExecutionBudget.Unavailable(
                kind = CoreExecutionClockFailureKind.CLOCK_GENERATION_CHANGED,
                detail = "Core clock generation changed during action execution",
                reading = current.reading,
            )
        }

        val localRemaining = saturatingSubtract(
            deadlineAtElapsedRealtimeMs,
            clock.elapsedRealtimeMs(),
        )
        val guaranteedRemaining = min(
            localRemaining,
            current.guaranteedRemainingMs,
        )
        if (guaranteedRemaining <= 0) {
            return CoreExecutionBudget.Unavailable(
                kind = CoreExecutionClockFailureKind.EXPIRED,
                detail = "command deadline elapsed before the next execution boundary",
                reading = current.reading,
            )
        }
        return CoreExecutionBudget.Available(
            milliseconds = min(requestedMilliseconds, guaranteedRemaining),
            reading = current.reading,
        )
    }

    private fun CoreDeadlineBudget.Unavailable.toExecutionBudget(): CoreExecutionBudget.Unavailable =
        CoreExecutionBudget.Unavailable(
            kind = when (kind) {
                CoreDeadlineUnavailableReason.INVALID_DEADLINE,
                CoreDeadlineUnavailableReason.CLOCK_UNAVAILABLE,
                -> CoreExecutionClockFailureKind.CLOCK_UNAVAILABLE

                CoreDeadlineUnavailableReason.UNCERTAINTY ->
                    CoreExecutionClockFailureKind.UNCERTAINTY

                CoreDeadlineUnavailableReason.EXPIRED ->
                    CoreExecutionClockFailureKind.EXPIRED
            },
            detail = reason,
            reading = reading,
        )

    private fun saturatingAdd(left: Long, right: Long): Long = when {
        right > 0 && left > Long.MAX_VALUE - right -> Long.MAX_VALUE
        right < 0 && left < Long.MIN_VALUE - right -> Long.MIN_VALUE
        else -> left + right
    }

    private fun saturatingSubtract(left: Long, right: Long): Long = when {
        right > 0 && left < Long.MIN_VALUE + right -> Long.MIN_VALUE
        right < 0 && left > Long.MAX_VALUE + right -> Long.MAX_VALUE
        else -> left - right
    }
}

fun CoreClock.beginExecutionLease(
    issuedAtCoreTimeMs: Long,
    deadlineAtCoreTimeMs: Long,
): CoreExecutionLeaseStart {
    val deadline = deadlineBudget(deadlineAtCoreTimeMs)
    if (deadline is CoreDeadlineBudget.Unavailable) {
        return CoreExecutionLeaseStart.Unavailable(
            kind = when (deadline.kind) {
                CoreDeadlineUnavailableReason.INVALID_DEADLINE,
                CoreDeadlineUnavailableReason.CLOCK_UNAVAILABLE,
                -> CoreExecutionClockFailureKind.CLOCK_UNAVAILABLE

                CoreDeadlineUnavailableReason.UNCERTAINTY ->
                    CoreExecutionClockFailureKind.UNCERTAINTY

                CoreDeadlineUnavailableReason.EXPIRED ->
                    CoreExecutionClockFailureKind.EXPIRED
            },
            detail = deadline.reason,
            fallbackCoreTimeMs = deadline.reading?.estimatedCoreTimeMs
                ?: issuedAtCoreTimeMs.coerceAtLeast(0),
            reading = deadline.reading,
        )
    }
    deadline as CoreDeadlineBudget.Available
    val reading = deadline.reading
    if (reading.latestCoreTimeMs < issuedAtCoreTimeMs) {
        return CoreExecutionLeaseStart.Unavailable(
            kind = CoreExecutionClockFailureKind.ISSUED_AT_IN_FUTURE,
            detail = "command issued_at_ms is later than the bounded current Core time",
            fallbackCoreTimeMs = reading.estimatedCoreTimeMs
                .coerceAtLeast(issuedAtCoreTimeMs)
                .coerceAtLeast(0),
            reading = reading,
        )
    }

    val localDeadline = saturatingAdd(
        reading.observedAtElapsedRealtimeMs,
        deadline.guaranteedRemainingMs,
    )
    return CoreExecutionLeaseStart.Available(
        CoreExecutionLease(
            clock = this,
            generation = reading.generation,
            startedAtElapsedRealtimeMs = reading.observedAtElapsedRealtimeMs,
            startedAtCoreTimeMs = reading.estimatedCoreTimeMs
                .coerceAtLeast(issuedAtCoreTimeMs)
                .coerceAtLeast(0),
            initialUncertaintyMs = reading.uncertaintyMs,
            deadlineAtCoreTimeMs = deadlineAtCoreTimeMs,
            deadlineAtElapsedRealtimeMs = localDeadline,
        )
    )
}

private fun saturatingAdd(left: Long, right: Long): Long = when {
    right > 0 && left > Long.MAX_VALUE - right -> Long.MAX_VALUE
    right < 0 && left < Long.MIN_VALUE - right -> Long.MIN_VALUE
    else -> left + right
}
