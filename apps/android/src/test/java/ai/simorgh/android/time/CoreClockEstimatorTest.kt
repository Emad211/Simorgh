package ai.simorgh.android.time

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CoreClockEstimatorTest {
    @Test
    fun `midpoint estimate exposes bounded uncertainty under positive skew`() {
        val clocks = MutableClocks(elapsedMs = 100, wallMs = 50_000)
        val estimator = estimator(clocks)
        estimator.beginGeneration(1)

        clocks.elapsedMs = 140
        clocks.wallMs = 50_040
        val outcome = estimator.recordSample(
            sampleGeneration = 1,
            requestSentElapsedMs = 100,
            responseReceivedElapsedMs = 140,
            serverTimeMs = 10_000,
            responseReceivedWallClockMs = clocks.wallMs,
        )

        assertTrue(outcome.accepted)
        val reading = requireNotNull(outcome.reading)
        assertEquals(10_000, reading.earliestCoreTimeMs)
        assertEquals(10_040, reading.latestCoreTimeMs)
        assertEquals(10_020, reading.estimatedCoreTimeMs)
        assertEquals(20, reading.uncertaintyMs)
        assertEquals(40, reading.lastRoundTripTimeMs)
    }

    @Test
    fun `negative device skew does not affect estimated Core epoch`() {
        val clocks = MutableClocks(elapsedMs = 1_000, wallMs = 9_000_000)
        val estimator = estimator(clocks)
        estimator.beginGeneration(2)

        clocks.elapsedMs = 1_040
        val outcome = estimator.recordSample(
            sampleGeneration = 2,
            requestSentElapsedMs = 1_000,
            responseReceivedElapsedMs = 1_040,
            serverTimeMs = 50,
            responseReceivedWallClockMs = clocks.wallMs + 40,
        )

        val reading = requireNotNull(outcome.reading)
        assertEquals(50, reading.earliestCoreTimeMs)
        assertEquals(90, reading.latestCoreTimeMs)
        assertEquals(70, reading.estimatedCoreTimeMs)
    }

    @Test
    fun `overlapping heartbeat samples intersect offset bounds conservatively`() {
        val clocks = MutableClocks(elapsedMs = 0, wallMs = 100_000)
        val estimator = estimator(clocks)
        estimator.beginGeneration(3)

        clocks.elapsedMs = 100
        estimator.recordSample(
            sampleGeneration = 3,
            requestSentElapsedMs = 0,
            responseReceivedElapsedMs = 100,
            serverTimeMs = 1_050,
            responseReceivedWallClockMs = 100_100,
        )
        clocks.elapsedMs = 200
        val outcome = estimator.recordSample(
            sampleGeneration = 3,
            requestSentElapsedMs = 160,
            responseReceivedElapsedMs = 200,
            serverTimeMs = 1_170,
            responseReceivedWallClockMs = 100_200,
        )

        val reading = requireNotNull(outcome.reading)
        assertEquals(1_170, reading.earliestCoreTimeMs)
        assertEquals(1_210, reading.latestCoreTimeMs)
        assertEquals(20, reading.uncertaintyMs)
        assertEquals(2, reading.sampleCount)
    }

    @Test
    fun `high RTT remains represented as uncertainty rather than hidden precision`() {
        val clocks = MutableClocks(elapsedMs = 0, wallMs = 10_000)
        val estimator = estimator(clocks)
        estimator.beginGeneration(4)

        clocks.elapsedMs = 1_000
        val outcome = estimator.recordSample(
            sampleGeneration = 4,
            requestSentElapsedMs = 0,
            responseReceivedElapsedMs = 1_000,
            serverTimeMs = 20_000,
            responseReceivedWallClockMs = 11_000,
        )

        val reading = requireNotNull(outcome.reading)
        assertEquals(500, reading.uncertaintyMs)
        assertEquals(1_000, reading.lastRoundTripTimeMs)
    }

    @Test
    fun `deadline uncertainty and definite expiry remain distinct`() {
        val clocks = MutableClocks(elapsedMs = 0, wallMs = 10_000)
        val estimator = estimator(clocks)
        estimator.beginGeneration(5)
        clocks.elapsedMs = 1_000
        estimator.recordSample(
            sampleGeneration = 5,
            requestSentElapsedMs = 0,
            responseReceivedElapsedMs = 1_000,
            serverTimeMs = 20_000,
            responseReceivedWallClockMs = 11_000,
        )

        val reading = requireNotNull(estimator.reading())
        val uncertain = estimator.deadlineBudget(reading.latestCoreTimeMs)
        assertTrue(uncertain is CoreDeadlineBudget.Unavailable)
        uncertain as CoreDeadlineBudget.Unavailable
        assertEquals(CoreDeadlineUnavailableReason.UNCERTAINTY, uncertain.kind)

        val expired = estimator.deadlineBudget(reading.earliestCoreTimeMs)
        assertTrue(expired is CoreDeadlineBudget.Unavailable)
        expired as CoreDeadlineBudget.Unavailable
        assertEquals(CoreDeadlineUnavailableReason.EXPIRED, expired.kind)

        val safe = estimator.deadlineBudget(reading.latestCoreTimeMs + 2_000)
        assertTrue(safe is CoreDeadlineBudget.Available)
        assertEquals(
            2_000,
            (safe as CoreDeadlineBudget.Available).guaranteedRemainingMs,
        )
    }

    @Test
    fun `large wall clock jump is detected without moving monotonic Core estimate`() {
        val clocks = MutableClocks(elapsedMs = 0, wallMs = 100_000)
        val estimator = estimator(clocks, wallClockJumpThresholdMs = 1_000)
        estimator.beginGeneration(6)

        clocks.elapsedMs = 100
        clocks.wallMs = 100_100
        estimator.recordSample(
            sampleGeneration = 6,
            requestSentElapsedMs = 50,
            responseReceivedElapsedMs = 100,
            serverTimeMs = 1_000_100,
            responseReceivedWallClockMs = clocks.wallMs,
        )
        val before = requireNotNull(estimator.reading())

        clocks.elapsedMs = 200
        clocks.wallMs = 900_000
        val outcome = estimator.recordSample(
            sampleGeneration = 6,
            requestSentElapsedMs = 150,
            responseReceivedElapsedMs = 200,
            serverTimeMs = 1_000_200,
            responseReceivedWallClockMs = clocks.wallMs,
        )

        assertTrue(outcome.wallClockJumpDetected)
        val after = requireNotNull(outcome.reading)
        assertEquals(1, after.wallClockJumpCount)
        assertTrue(after.estimatedCoreTimeMs >= before.estimatedCoreTimeMs)
    }

    @Test
    fun `large Core discontinuity requires a confirming sample`() {
        val clocks = MutableClocks(elapsedMs = 0, wallMs = 100_000)
        val estimator = estimator(clocks, coreDiscontinuityThresholdMs = 100)
        estimator.beginGeneration(7)

        clocks.elapsedMs = 20
        estimator.recordSample(
            sampleGeneration = 7,
            requestSentElapsedMs = 0,
            responseReceivedElapsedMs = 20,
            serverTimeMs = 10_010,
            responseReceivedWallClockMs = 100_020,
        )
        clocks.elapsedMs = 120
        val discontinuity = estimator.recordSample(
            sampleGeneration = 7,
            requestSentElapsedMs = 100,
            responseReceivedElapsedMs = 120,
            serverTimeMs = 50_110,
            responseReceivedWallClockMs = 100_120,
        )

        assertTrue(discontinuity.coreDiscontinuityDetected)
        assertNull(discontinuity.reading)
        assertNull(estimator.reading())

        clocks.elapsedMs = 220
        val confirmation = estimator.recordSample(
            sampleGeneration = 7,
            requestSentElapsedMs = 200,
            responseReceivedElapsedMs = 220,
            serverTimeMs = 50_210,
            responseReceivedWallClockMs = 100_220,
        )
        assertFalse(confirmation.coreDiscontinuityDetected)
        assertEquals(1, requireNotNull(confirmation.reading).discontinuityCount)
    }

    @Test
    fun `reconnect generation invalidates old estimate and accepts new epoch`() {
        val clocks = MutableClocks(elapsedMs = 0, wallMs = 1_000)
        val estimator = estimator(clocks)
        estimator.beginGeneration(8)
        clocks.elapsedMs = 20
        estimator.recordSample(8, 0, 20, 10_010, 1_020)
        assertEquals(8, requireNotNull(estimator.reading()).generation)

        estimator.beginGeneration(9)
        assertNull(estimator.reading())
        val obsolete = estimator.recordSample(8, 20, 40, 10_030, 1_040)
        assertFalse(obsolete.accepted)

        clocks.elapsedMs = 60
        val current = estimator.recordSample(9, 40, 60, 90_050, 1_060)
        assertEquals(9, requireNotNull(current.reading).generation)
    }

    @Test
    fun `estimate becomes unavailable after maximum sample age`() {
        val clocks = MutableClocks(elapsedMs = 0, wallMs = 1_000)
        val estimator = estimator(clocks, maximumEstimateAgeMs = 100)
        estimator.beginGeneration(10)
        clocks.elapsedMs = 20
        estimator.recordSample(10, 0, 20, 10_010, 1_020)
        assertTrue(estimator.reading() != null)

        clocks.elapsedMs = 121
        assertNull(estimator.reading())
    }

    private fun estimator(
        clocks: MutableClocks,
        maximumEstimateAgeMs: Long = 10_000,
        wallClockJumpThresholdMs: Long = 2_000,
        coreDiscontinuityThresholdMs: Long = 2_000,
    ): CoreClockEstimator = CoreClockEstimator(
        monotonicMillis = { clocks.elapsedMs },
        wallClockMillis = { clocks.wallMs },
        maximumEstimateAgeMs = maximumEstimateAgeMs,
        wallClockJumpThresholdMs = wallClockJumpThresholdMs,
        coreDiscontinuityThresholdMs = coreDiscontinuityThresholdMs,
    )

    private data class MutableClocks(
        var elapsedMs: Long,
        var wallMs: Long,
    )
}
