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

class OpenAppActionEvidenceDeadlineTest {
    @Test
    fun `satisfied evidence captured at conservative deadline is timed out`() {
        val clock = MutableCoreClock(elapsedMs = 5_000)
        val beforeSnapshot = snapshot(
            id = BEFORE_SNAPSHOT_ID,
            capturedAtElapsedMs = 4_950,
            activePackage = SOURCE_PACKAGE,
        )
        val before = acknowledged(1, beforeSnapshot)
        val fresh = beforeSnapshot.copy(
            snapshotId = FRESH_SNAPSHOT_ID,
            capturedAtElapsedRealtimeMs = 5_050,
        )
        val afterSnapshot = snapshot(
            id = AFTER_SNAPSHOT_ID,
            capturedAtElapsedMs = 5_200,
            activePackage = TARGET_PACKAGE,
        )
        val verification = AndroidVerificationPolicy(
            predicates = listOf(ActivePackageEqualsPredicate(TARGET_PACKAGE)),
            timeoutMs = 1_000,
            stableSamples = 1,
        )
        val evidence = DeadlineEvidenceSource(
            before = before,
            fresh = fresh,
            result = PostActionEvidenceResult(
                status = PostActionEvidenceStatus.SATISFIED,
                observation = acknowledged(2, afterSnapshot),
                evaluation = UiPostconditionEvaluator.evaluate(afterSnapshot, verification),
                detail = "fixture evidence captured at deadline",
            ),
            onFresh = { clock.elapsedMs = 5_050 },
            onAwait = { clock.elapsedMs = 5_250 },
        )
        val completed = CountDownLatch(1)
        val result = AtomicReference<AndroidActionResult?>()
        val executor = OpenAppActionExecutor(
            launcher = OpenAppLauncher {
                OpenAppLaunchAttempt(
                    status = OpenAppLaunchStatus.ACCEPTED,
                    adapter = "deadline_fixture",
                    detail = "accepted",
                )
            },
            evidenceSource = evidence,
            coreClock = clock,
        )

        try {
            assertTrue(
                executor.submit(
                    ReceivedAndroidAction(
                        commandEnvelopeId = COMMAND_ENVELOPE_ID,
                        command = command(verification),
                    ),
                    AndroidActionCompletion { value ->
                        result.set(value)
                        completed.countDown()
                    },
                ),
            )
            assertTrue(completed.await(2, TimeUnit.SECONDS))
            val actual = requireNotNull(result.get())
            assertEquals(ActionOutcome.TIMED_OUT, actual.outcome)
            assertEquals(ActionFailureCode.OBSERVATION_TIMEOUT, actual.failureCode)
            assertEquals(1, actual.attempts)
            assertEquals(AFTER_SNAPSHOT_ID, actual.afterObservation?.snapshotId)
            assertTrue(actual.detail.contains("outside the action deadline"))
        } finally {
            executor.close()
        }
    }

    private fun command(
        verification: AndroidVerificationPolicy,
    ): AndroidActionCommand = AndroidActionContractValidator.validate(
        AndroidActionCommand(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            issuedAtMs = 9_000,
            deadlineAtMs = 10_200,
            precondition = ObservationPrecondition(
                expectedStreamId = STREAM_ID,
                minimumSequence = 1,
                expectedActivePackage = SOURCE_PACKAGE,
                maximumAgeMs = 2_000,
            ),
            operation = OpenAppOperation(packageName = TARGET_PACKAGE),
            verification = verification,
        ),
    )

    private fun snapshot(
        id: String,
        capturedAtElapsedMs: Long,
        activePackage: String,
    ): AccessibilitySnapshot = AccessibilitySnapshot(
        snapshotId = id,
        capturedAtMs = 500_000 + capturedAtElapsedMs,
        capturedAtElapsedRealtimeMs = capturedAtElapsedMs,
        activePackage = activePackage,
        activeWindowId = 1,
        windows = emptyList(),
        nodes = emptyList(),
        truncated = false,
        truncationReasons = emptyList(),
        maxDepthObserved = 0,
    )

    private fun acknowledged(
        sequence: Long,
        snapshot: AccessibilitySnapshot,
    ): AcknowledgedAccessibilityObservation = AcknowledgedAccessibilityObservation(
        streamId = STREAM_ID,
        sequence = sequence,
        stateFingerprint = AccessibilitySnapshotFingerprint.calculate(snapshot),
        snapshot = snapshot,
        acknowledgedAtMs = 10_000 + sequence,
    )

    private class MutableCoreClock(
        var elapsedMs: Long,
    ) : CoreClock {
        private val stableReading = CoreClockReading(
            generation = 1,
            estimatedCoreTimeMs = 10_000,
            earliestCoreTimeMs = 10_000,
            latestCoreTimeMs = 10_000,
            uncertaintyMs = 0,
            sampleAgeMs = 0,
            lastRoundTripTimeMs = 0,
            sampleCount = 1,
            discontinuityCount = 0,
            wallClockJumpCount = 0,
            observedAtElapsedRealtimeMs = 5_000,
        )

        override fun elapsedRealtimeMs(): Long = elapsedMs

        override fun reading(): CoreClockReading = stableReading

        override fun deadlineBudget(deadlineCoreTimeMs: Long): CoreDeadlineBudget {
            val earliestRemaining = deadlineCoreTimeMs - stableReading.earliestCoreTimeMs
            if (earliestRemaining <= 0) {
                return CoreDeadlineBudget.Unavailable(
                    kind = CoreDeadlineUnavailableReason.EXPIRED,
                    reason = "fixture deadline definitely elapsed",
                    reading = stableReading,
                )
            }
            val guaranteed = deadlineCoreTimeMs - stableReading.latestCoreTimeMs
            return CoreDeadlineBudget.Available(guaranteed, stableReading)
        }
    }

    private class DeadlineEvidenceSource(
        private val before: AcknowledgedAccessibilityObservation,
        private val fresh: AccessibilitySnapshot,
        private val result: PostActionEvidenceResult,
        private val onFresh: () -> Unit,
        private val onAwait: () -> Unit,
    ) : OpenAppEvidenceSource {
        override fun latestAcknowledged(): AcknowledgedAccessibilityObservation = before

        override fun requestFreshLocalSnapshot(
            timeoutMillis: Long,
            cancelled: () -> Boolean,
        ): AccessibilitySnapshot {
            onFresh()
            return fresh
        }

        override fun awaitVerifiedObservation(
            before: AcknowledgedAccessibilityObservation,
            launchedAtElapsedRealtimeMs: Long,
            policy: AndroidVerificationPolicy,
            timeoutMillis: Long,
            cancelled: () -> Boolean,
        ): PostActionEvidenceResult {
            onAwait()
            return result
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
        const val AFTER_SNAPSHOT_ID = "77777777-7777-7777-7777-777777777777"
    }
}
