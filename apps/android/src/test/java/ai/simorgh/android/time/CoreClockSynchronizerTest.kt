package ai.simorgh.android.time

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

class CoreClockSynchronizerTest {
    @Test
    fun `registration correlation seeds the active generation`() {
        val clocks = MutableClocks(elapsedMs = 100, wallMs = 1_000)
        val estimator = estimator(clocks)
        val synchronizer = synchronizer(clocks, estimator)
        val registrationId = UUID.randomUUID().toString()

        synchronizer.beginGeneration(10)
        assertTrue(synchronizer.markRegistrationSent(10, registrationId))
        clocks.elapsedMs = 140
        clocks.wallMs = 1_040
        val outcome = synchronizer.acceptRegistration(
            generation = 10,
            correlationId = registrationId,
            serverTimeMs = 50_000,
        )

        assertTrue(outcome.accepted)
        assertFalse(outcome.fatal)
        val reading = requireNotNull(outcome.reading)
        assertEquals(10, reading.generation)
        assertEquals(40, reading.lastRoundTripTimeMs)
        assertEquals(20, reading.uncertaintyMs)
    }

    @Test
    fun `registration with mismatched correlation fails closed`() {
        val clocks = MutableClocks(100, 1_000)
        val synchronizer = synchronizer(clocks, estimator(clocks))
        synchronizer.beginGeneration(11)
        assertTrue(synchronizer.markRegistrationSent(11, UUID.randomUUID().toString()))

        val outcome = synchronizer.acceptRegistration(
            generation = 11,
            correlationId = UUID.randomUUID().toString(),
            serverTimeMs = 10_000,
        )

        assertFalse(outcome.accepted)
        assertTrue(outcome.fatal)
        assertEquals(CoreClockSyncFailureKind.INVALID_IDENTITY, outcome.failureKind)
        assertNull(outcome.reading)
    }

    @Test
    fun `heartbeat sequence mismatch is fatal and does not update estimate`() {
        val clocks = MutableClocks(0, 1_000)
        val estimator = estimator(clocks)
        val synchronizer = synchronizer(clocks, estimator)
        synchronizer.beginGeneration(12)
        val registrationId = UUID.randomUUID().toString()
        synchronizer.markRegistrationSent(12, registrationId)
        clocks.elapsedMs = 20
        synchronizer.acceptRegistration(12, registrationId, 10_010)
        val before = requireNotNull(estimator.reading())

        val heartbeatId = UUID.randomUUID().toString()
        clocks.elapsedMs = 100
        assertTrue(synchronizer.markHeartbeatSent(12, heartbeatId, sequence = 1))
        clocks.elapsedMs = 120
        val outcome = synchronizer.acceptHeartbeat(
            generation = 12,
            correlationId = heartbeatId,
            sequence = 2,
            serverTimeMs = 10_110,
        )

        assertFalse(outcome.accepted)
        assertTrue(outcome.fatal)
        assertEquals(CoreClockSyncFailureKind.SEQUENCE_MISMATCH, outcome.failureKind)
        assertEquals(before.sampleCount, requireNotNull(estimator.reading()).sampleCount)
    }

    @Test
    fun `unknown late heartbeat is ignored without corrupting current clock`() {
        val clocks = MutableClocks(0, 1_000)
        val estimator = estimator(clocks)
        val synchronizer = synchronizer(clocks, estimator)
        synchronizer.beginGeneration(13)
        val registrationId = UUID.randomUUID().toString()
        synchronizer.markRegistrationSent(13, registrationId)
        clocks.elapsedMs = 20
        synchronizer.acceptRegistration(13, registrationId, 10_010)

        val outcome = synchronizer.acceptHeartbeat(
            generation = 13,
            correlationId = UUID.randomUUID().toString(),
            sequence = 99,
            serverTimeMs = 10_020,
        )

        assertFalse(outcome.accepted)
        assertFalse(outcome.fatal)
        assertEquals(CoreClockSyncFailureKind.UNKNOWN_PROBE, outcome.failureKind)
        assertEquals(1, requireNotNull(outcome.reading).sampleCount)
    }

    @Test
    fun `new socket generation rejects probes from the previous reconnect`() {
        val clocks = MutableClocks(0, 1_000)
        val estimator = estimator(clocks)
        val synchronizer = synchronizer(clocks, estimator)
        val oldRegistration = UUID.randomUUID().toString()
        synchronizer.beginGeneration(14)
        synchronizer.markRegistrationSent(14, oldRegistration)

        synchronizer.beginGeneration(15)
        val obsolete = synchronizer.acceptRegistration(
            generation = 14,
            correlationId = oldRegistration,
            serverTimeMs = 10_000,
        )
        assertFalse(obsolete.accepted)
        assertFalse(obsolete.fatal)
        assertEquals(CoreClockSyncFailureKind.INACTIVE_GENERATION, obsolete.failureKind)
        assertNull(estimator.reading())

        val currentRegistration = UUID.randomUUID().toString()
        synchronizer.markRegistrationSent(15, currentRegistration)
        clocks.elapsedMs = 20
        val current = synchronizer.acceptRegistration(
            generation = 15,
            correlationId = currentRegistration,
            serverTimeMs = 20_010,
        )
        assertEquals(15, requireNotNull(current.reading).generation)
    }

    @Test
    fun `bounded heartbeat probes evict oldest without making late ack fatal`() {
        val clocks = MutableClocks(0, 1_000)
        val estimator = estimator(clocks)
        val synchronizer = CoreClockSynchronizer(
            estimator = estimator,
            monotonicMillis = { clocks.elapsedMs },
            wallClockMillis = { clocks.wallMs },
            maxPendingHeartbeatProbes = 2,
        )
        synchronizer.beginGeneration(16)
        val registrationId = UUID.randomUUID().toString()
        synchronizer.markRegistrationSent(16, registrationId)
        clocks.elapsedMs = 10
        synchronizer.acceptRegistration(16, registrationId, 10_005)

        val first = UUID.randomUUID().toString()
        val second = UUID.randomUUID().toString()
        val third = UUID.randomUUID().toString()
        synchronizer.markHeartbeatSent(16, first, 1)
        synchronizer.markHeartbeatSent(16, second, 2)
        synchronizer.markHeartbeatSent(16, third, 3)

        val evicted = synchronizer.acceptHeartbeat(16, first, 1, 10_020)
        assertFalse(evicted.accepted)
        assertFalse(evicted.fatal)
        assertEquals(CoreClockSyncFailureKind.UNKNOWN_PROBE, evicted.failureKind)

        clocks.elapsedMs = 20
        val current = synchronizer.acceptHeartbeat(16, third, 3, 10_015)
        assertTrue(current.accepted)
    }

    private fun estimator(clocks: MutableClocks): CoreClockEstimator = CoreClockEstimator(
        monotonicMillis = { clocks.elapsedMs },
        wallClockMillis = { clocks.wallMs },
        maximumEstimateAgeMs = 10_000,
        wallClockJumpThresholdMs = 1_000,
        coreDiscontinuityThresholdMs = 1_000,
    )

    private fun synchronizer(
        clocks: MutableClocks,
        estimator: CoreClockEstimator,
    ): CoreClockSynchronizer = CoreClockSynchronizer(
        estimator = estimator,
        monotonicMillis = { clocks.elapsedMs },
        wallClockMillis = { clocks.wallMs },
    )

    private data class MutableClocks(
        var elapsedMs: Long,
        var wallMs: Long,
    )
}
