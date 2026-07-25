package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.accessibility.AcknowledgedAccessibilityObservation
import ai.simorgh.android.time.CoreClock
import ai.simorgh.android.time.CoreClockReading
import ai.simorgh.android.time.CoreDeadlineBudget
import ai.simorgh.android.time.CoreDeadlineUnavailableReason
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class OpenAppActionExceptionClockTest {
    @Test
    fun `exception after accepted launch uses lease duration instead of jumped estimate`() {
        val clock = MutableCoreClock(
            elapsedMs = 5_000,
            reading = reading(
                observedAtElapsedMs = 5_000,
                estimatedCoreMs = 10_000,
            ),
        )
        val beforeSnapshot = snapshot(
            id = BEFORE_SNAPSHOT_ID,
            capturedAtElapsedMs = 4_500,
            activePackage = SOURCE_PACKAGE,
        )
        val before = AcknowledgedAccessibilityObservation(
            streamId = STREAM_ID,
            sequence = 1,
            stateFingerprint = AccessibilitySnapshotFingerprint.calculate(beforeSnapshot),
            snapshot = beforeSnapshot,
            acknowledgedAtMs = 10_000,
        )
        val fresh = beforeSnapshot.copy(
            snapshotId = FRESH_SNAPSHOT_ID,
            capturedAtElapsedRealtimeMs = 5_050,
        )
        val evidence = ThrowingPostLaunchEvidenceSource(
            before = before,
            fresh = fresh,
            beforeThrow = {
                clock.elapsedMs = 5_200
                clock.reading = reading(
                    observedAtElapsedMs = 5_200,
                    estimatedCoreMs = 900_000,
                )
            },
        )
        val completed = CountDownLatch(1)
        val result = AtomicReference<AndroidActionResult?>()
        val executor = OpenAppActionExecutor(
            launcher = OpenAppLauncher {
                OpenAppLaunchAttempt(
                    status = OpenAppLaunchStatus.ACCEPTED,
                    adapter = "exception_clock_fixture",
                    detail = "accepted",
                )
            },
            evidenceSource = evidence,
            coreClock = clock,
        )

        try {
            assertTrue(
                executor.submit(
                    ReceivedAndroidAction(COMMAND_ENVELOPE_ID, command()),
                    AndroidActionCompletion { value ->
                        result.set(value)
                        completed.countDown()
                    },
                ),
            )
            assertTrue(completed.await(2, TimeUnit.SECONDS))
            val actual = requireNotNull(result.get())
            assertEquals(ActionOutcome.BLOCKED, actual.outcome)
            assertEquals(ActionFailureCode.INTERNAL_ERROR, actual.failureCode)
            assertEquals(1, actual.attempts)
            assertEquals(10_000, actual.startedAtMs)
            assertEquals(10_200, actual.finishedAtMs)
            assertTrue(actual.detail.contains("IllegalStateException"))
        } finally {
            executor.close()
        }
    }

    private fun command(): AndroidActionCommand = AndroidActionContractValidator.validate(
        AndroidActionCommand(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            issuedAtMs = 9_000,
            deadlineAtMs = 20_000,
            precondition = ObservationPrecondition(
                expectedStreamId = STREAM_ID,
                minimumSequence = 1,
                expectedActivePackage = SOURCE_PACKAGE,
                maximumAgeMs = 2_000,
            ),
            operation = OpenAppOperation(packageName = TARGET_PACKAGE),
            verification = AndroidVerificationPolicy(
                predicates = listOf(ActivePackageEqualsPredicate(TARGET_PACKAGE)),
                timeoutMs = 1_000,
                stableSamples = 1,
            ),
        ),
    )

    private fun snapshot(
        id: String,
        capturedAtElapsedMs: Long,
        activePackage: String,
    ): AccessibilitySnapshot = AccessibilitySnapshot(
        snapshotId = id,
        capturedAtMs = 123_456,
        capturedAtElapsedRealtimeMs = capturedAtElapsedMs,
        activePackage = activePackage,
        activeWindowId = 1,
        windows = emptyList(),
        nodes = emptyList(),
        truncated = false,
        truncationReasons = emptyList(),
        maxDepthObserved = 0,
    )

    private fun reading(
        observedAtElapsedMs: Long,
        estimatedCoreMs: Long,
    ): CoreClockReading = CoreClockReading(
        generation = 1,
        estimatedCoreTimeMs = estimatedCoreMs,
        earliestCoreTimeMs = estimatedCoreMs,
        latestCoreTimeMs = estimatedCoreMs,
        uncertaintyMs = 0,
        sampleAgeMs = 0,
        lastRoundTripTimeMs = 0,
        sampleCount = 1,
        discontinuityCount = 0,
        wallClockJumpCount = 0,
        observedAtElapsedRealtimeMs = observedAtElapsedMs,
    )

    private class MutableCoreClock(
        var elapsedMs: Long,
        var reading: CoreClockReading,
    ) : CoreClock {
        override fun elapsedRealtimeMs(): Long = elapsedMs

        override fun reading(): CoreClockReading = reading

        override fun deadlineBudget(deadlineCoreTimeMs: Long): CoreDeadlineBudget {
            val earliestRemaining = deadlineCoreTimeMs - reading.earliestCoreTimeMs
            if (earliestRemaining <= 0) {
                return CoreDeadlineBudget.Unavailable(
                    kind = CoreDeadlineUnavailableReason.EXPIRED,
                    reason = "fixture deadline definitely elapsed",
                    reading = reading,
                )
            }
            val guaranteed = deadlineCoreTimeMs - reading.latestCoreTimeMs
            return if (guaranteed > 0) {
                CoreDeadlineBudget.Available(guaranteed, reading)
            } else {
                CoreDeadlineBudget.Unavailable(
                    kind = CoreDeadlineUnavailableReason.UNCERTAINTY,
                    reason = "fixture uncertainty overlaps deadline",
                    reading = reading,
                )
            }
        }
    }

    private class ThrowingPostLaunchEvidenceSource(
        private val before: AcknowledgedAccessibilityObservation,
        private val fresh: AccessibilitySnapshot,
        private val beforeThrow: () -> Unit,
    ) : OpenAppEvidenceSource {
        override fun latestAcknowledged(): AcknowledgedAccessibilityObservation = before

        override fun requestFreshLocalSnapshot(
            timeoutMillis: Long,
            cancelled: () -> Boolean,
        ): AccessibilitySnapshot = fresh

        override fun awaitVerifiedObservation(
            before: AcknowledgedAccessibilityObservation,
            launchedAtElapsedRealtimeMs: Long,
            policy: AndroidVerificationPolicy,
            timeoutMillis: Long,
            cancelled: () -> Boolean,
        ): PostActionEvidenceResult {
            beforeThrow()
            throw IllegalStateException("post-launch fixture failure")
        }

        override fun close() = Unit
    }

    private companion object {
        const val SOURCE_PACKAGE = "com.example.source"
        const val TARGET_PACKAGE = "com.example.target"
        const val STREAM_ID = "11111111-1111-1111-1111-111111111111"
        const val COMMAND_ENVELOPE_ID = "22222222-2222-2222-2222-222222222222"
        const val COMMAND_ID = "33333333-3333-3333-3333-333333333333"
        const val ACTION_ID = "44444444-4444-4444-4444-444444444444"
        const val BEFORE_SNAPSHOT_ID = "55555555-5555-5555-5555-555555555555"
        const val FRESH_SNAPSHOT_ID = "66666666-6666-6666-6666-666666666666"
    }
}
