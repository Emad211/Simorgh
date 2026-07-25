package ai.simorgh.android.time

/**
 * Compatibility adapter for deterministic JVM fixtures that historically supplied one synthetic
 * wall clock. Production code must use [CoreClockBus].
 */
internal class LegacyWallClockCoreClock(
    private val coreTimeMillis: () -> Long,
    private val elapsedMillis: () -> Long = coreTimeMillis,
) : CoreClock {
    override fun elapsedRealtimeMs(): Long = elapsedMillis().coerceAtLeast(0)

    override fun reading(): CoreClockReading {
        val now = coreTimeMillis().coerceAtLeast(0)
        return CoreClockReading(
            generation = 0,
            estimatedCoreTimeMs = now,
            earliestCoreTimeMs = now,
            latestCoreTimeMs = now,
            uncertaintyMs = 0,
            sampleAgeMs = 0,
            lastRoundTripTimeMs = 0,
            sampleCount = 1,
            discontinuityCount = 0,
            wallClockJumpCount = 0,
            observedAtElapsedRealtimeMs = elapsedRealtimeMs(),
        )
    }

    override fun deadlineBudget(deadlineCoreTimeMs: Long): CoreDeadlineBudget {
        if (deadlineCoreTimeMs < 0) {
            return CoreDeadlineBudget.Unavailable(
                kind = CoreDeadlineUnavailableReason.INVALID_DEADLINE,
                reason = "deadline cannot be negative",
            )
        }
        val reading = reading()
        val remaining = deadlineCoreTimeMs - reading.latestCoreTimeMs
        return if (remaining > 0) {
            CoreDeadlineBudget.Available(
                guaranteedRemainingMs = remaining,
                reading = reading,
            )
        } else {
            CoreDeadlineBudget.Unavailable(
                kind = CoreDeadlineUnavailableReason.EXPIRED,
                reason = "command deadline has elapsed",
                reading = reading,
            )
        }
    }
}
