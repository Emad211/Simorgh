package ai.simorgh.android.time

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CoreExecutionLeaseTest {
    @Test
    fun `lease never extends beyond initial guaranteed deadline`() {
        val clock = MutableCoreClock(
            reading = reading(
                generation = 1,
                observedAtElapsedMs = 100,
                estimatedCoreMs = 10_000,
                latestCoreMs = 10_020,
                uncertaintyMs = 20,
            ),
            elapsedMs = 100,
        )
        val started = clock.beginExecutionLease(
            issuedAtCoreTimeMs = 9_900,
            deadlineAtCoreTimeMs = 11_020,
        )
        assertTrue(started is CoreExecutionLeaseStart.Available)
        val lease = (started as CoreExecutionLeaseStart.Available).lease

        // A later sample claims much more Core budget, but the action keeps the original
        // elapsedRealtime deadline: 100 + (11020 - 10020) = 1100.
        clock.elapsedMs = 1_000
        clock.reading = reading(
            generation = 1,
            observedAtElapsedMs = 1_000,
            estimatedCoreMs = 10_100,
            latestCoreMs = 10_100,
            uncertaintyMs = 0,
        )
        val budget = lease.remainingBudget(5_000)

        assertTrue(budget is CoreExecutionBudget.Available)
        assertEquals(100, (budget as CoreExecutionBudget.Available).milliseconds)
    }

    @Test
    fun `lease fails closed after reconnect generation changes`() {
        val clock = MutableCoreClock(
            reading = reading(1, 100, 10_000, 10_010, 10),
            elapsedMs = 100,
        )
        val lease = (
            clock.beginExecutionLease(9_900, 11_000) as
                CoreExecutionLeaseStart.Available
            ).lease

        clock.elapsedMs = 200
        clock.reading = reading(2, 200, 10_100, 10_110, 10)
        val budget = lease.remainingBudget(500)

        assertTrue(budget is CoreExecutionBudget.Unavailable)
        assertEquals(
            CoreExecutionClockFailureKind.CLOCK_GENERATION_CHANGED,
            (budget as CoreExecutionBudget.Unavailable).kind,
        )
    }

    @Test
    fun `command issued in the future relative to bounded Core time is rejected`() {
        val clock = MutableCoreClock(
            reading = reading(3, 100, 10_000, 10_010, 10),
            elapsedMs = 100,
        )

        val start = clock.beginExecutionLease(
            issuedAtCoreTimeMs = 10_011,
            deadlineAtCoreTimeMs = 11_000,
        )

        assertTrue(start is CoreExecutionLeaseStart.Unavailable)
        assertEquals(
            CoreExecutionClockFailureKind.ISSUED_AT_IN_FUTURE,
            (start as CoreExecutionLeaseStart.Unavailable).kind,
        )
    }

    @Test
    fun `result timestamp advances only with elapsedRealtime`() {
        val clock = MutableCoreClock(
            reading = reading(4, 500, 50_000, 50_020, 20),
            elapsedMs = 500,
        )
        val lease = (
            clock.beginExecutionLease(49_000, 51_000) as
                CoreExecutionLeaseStart.Available
            ).lease

        clock.elapsedMs = 725
        clock.reading = reading(4, 725, 900_000, 900_000, 0)

        assertEquals(50_225, lease.coreTimeNowMs())
    }

    @Test
    fun `uncertainty smaller than no remaining budget is rejected before lease creation`() {
        val clock = MutableCoreClock(
            reading = reading(5, 100, 10_000, 10_100, 100),
            elapsedMs = 100,
        )

        val start = clock.beginExecutionLease(
            issuedAtCoreTimeMs = 9_000,
            deadlineAtCoreTimeMs = 10_100,
        )

        assertTrue(start is CoreExecutionLeaseStart.Unavailable)
        assertEquals(
            CoreExecutionClockFailureKind.UNCERTAINTY,
            (start as CoreExecutionLeaseStart.Unavailable).kind,
        )
    }

    private fun reading(
        generation: Long,
        observedAtElapsedMs: Long,
        estimatedCoreMs: Long,
        latestCoreMs: Long,
        uncertaintyMs: Long,
    ): CoreClockReading = CoreClockReading(
        generation = generation,
        observedAtElapsedRealtimeMs = observedAtElapsedMs,
        estimatedCoreTimeMs = estimatedCoreMs,
        earliestCoreTimeMs = estimatedCoreMs - uncertaintyMs,
        latestCoreTimeMs = latestCoreMs,
        uncertaintyMs = uncertaintyMs,
        sampleAgeMs = 0,
        lastRoundTripTimeMs = uncertaintyMs * 2,
        sampleCount = 1,
        discontinuityCount = 0,
        wallClockJumpCount = 0,
    )

    private class MutableCoreClock(
        var reading: CoreClockReading,
        var elapsedMs: Long,
    ) : CoreClock {
        override fun elapsedRealtimeMs(): Long = elapsedMs

        override fun reading(): CoreClockReading = reading

        override fun deadlineBudget(deadlineCoreTimeMs: Long): CoreDeadlineBudget {
            val centeredRemaining = deadlineCoreTimeMs - reading.estimatedCoreTimeMs
            if (centeredRemaining <= reading.uncertaintyMs) {
                return CoreDeadlineBudget.Unavailable(
                    kind = CoreDeadlineUnavailableReason.UNCERTAINTY,
                    reason = "uncertainty consumes deadline",
                    reading = reading,
                )
            }
            val guaranteed = deadlineCoreTimeMs - reading.latestCoreTimeMs
            return if (guaranteed > 0) {
                CoreDeadlineBudget.Available(guaranteed, reading)
            } else {
                CoreDeadlineBudget.Unavailable(
                    kind = CoreDeadlineUnavailableReason.EXPIRED,
                    reason = "deadline elapsed",
                    reading = reading,
                )
            }
        }
    }
}
