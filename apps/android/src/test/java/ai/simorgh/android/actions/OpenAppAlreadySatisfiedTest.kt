package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.accessibility.AcknowledgedAccessibilityObservation
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

class OpenAppAlreadySatisfiedTest {
    @Test
    fun `already active target succeeds with zero attempts and no launcher call`() {
        val acknowledgedSnapshot = snapshot(
            snapshotId = ACKNOWLEDGED_SNAPSHOT_ID,
            capturedAtMs = 9_500,
        )
        val acknowledged = AcknowledgedAccessibilityObservation(
            streamId = STREAM_ID,
            sequence = 9,
            stateFingerprint = AccessibilitySnapshotFingerprint.calculate(acknowledgedSnapshot),
            snapshot = acknowledgedSnapshot,
            acknowledgedAtMs = 9_510,
        )
        val freshSnapshot = acknowledgedSnapshot.copy(
            snapshotId = FRESH_SNAPSHOT_ID,
            capturedAtMs = NOW_MS,
        )
        val evidenceSource = AlreadySatisfiedEvidenceSource(
            acknowledged = acknowledged,
            fresh = freshSnapshot,
        )
        val launcherCalls = AtomicInteger(0)
        val executor = OpenAppActionExecutor(
            launcher = OpenAppLauncher {
                launcherCalls.incrementAndGet()
                OpenAppLaunchAttempt(
                    status = OpenAppLaunchStatus.ACCEPTED,
                    adapter = "unexpected",
                    detail = "launcher should not be called",
                )
            },
            evidenceSource = evidenceSource,
            wallClockMillis = { NOW_MS },
        )
        val completion = AtomicReference<AndroidActionResult?>()
        val completed = CountDownLatch(1)
        try {
            val accepted = executor.submit(
                request = ReceivedAndroidAction(
                    commandEnvelopeId = COMMAND_ENVELOPE_ID,
                    command = command(),
                ),
                completion = AndroidActionCompletion { result ->
                    completion.set(result)
                    completed.countDown()
                },
            )

            assertTrue(accepted)
            assertTrue(completed.await(2, TimeUnit.SECONDS))
            val result = requireNotNull(completion.get())
            assertEquals(ActionOutcome.SUCCEEDED, result.outcome)
            assertEquals(ActionFailureCode.NONE, result.failureCode)
            assertEquals(0, result.attempts)
            assertEquals(0, launcherCalls.get())
            assertEquals(0, evidenceSource.postWaitCalls)
            assertEquals(ACKNOWLEDGED_SNAPSHOT_ID, result.beforeObservation?.snapshotId)
            assertEquals(ACKNOWLEDGED_SNAPSHOT_ID, result.afterObservation?.snapshotId)
            assertEquals(PredicateOutcome.SATISFIED, result.predicates.single().outcome)
            assertTrue(result.detail.contains("launch was skipped"))
        } finally {
            executor.close()
        }
    }

    private fun command(): AndroidActionCommand = AndroidActionContractValidator.validate(
        AndroidActionCommand(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            issuedAtMs = NOW_MS - 1_000,
            deadlineAtMs = NOW_MS + 10_000,
            precondition = ObservationPrecondition(
                expectedStreamId = STREAM_ID,
                minimumSequence = 9,
                expectedActivePackage = TARGET_PACKAGE,
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
        snapshotId: String,
        capturedAtMs: Long,
    ): AccessibilitySnapshot = AccessibilitySnapshot(
        snapshotId = snapshotId,
        capturedAtMs = capturedAtMs,
        activePackage = TARGET_PACKAGE,
        activeWindowId = 1,
        windows = emptyList(),
        nodes = emptyList(),
        truncated = false,
        truncationReasons = emptyList(),
        maxDepthObserved = 0,
    )

    private class AlreadySatisfiedEvidenceSource(
        private val acknowledged: AcknowledgedAccessibilityObservation,
        private val fresh: AccessibilitySnapshot,
    ) : OpenAppEvidenceSource {
        var postWaitCalls: Int = 0
            private set

        override fun latestAcknowledged(): AcknowledgedAccessibilityObservation = acknowledged

        override fun requestFreshLocalSnapshot(
            timeoutMillis: Long,
            cancelled: () -> Boolean,
        ): AccessibilitySnapshot = fresh

        override fun awaitVerifiedObservation(
            before: AcknowledgedAccessibilityObservation,
            launchedAtMs: Long,
            policy: AndroidVerificationPolicy,
            timeoutMillis: Long,
            cancelled: () -> Boolean,
        ): PostActionEvidenceResult {
            postWaitCalls += 1
            return PostActionEvidenceResult(PostActionEvidenceStatus.OBSERVATION_TIMEOUT)
        }

        override fun close() = Unit
    }

    private companion object {
        const val NOW_MS = 10_000L
        const val COMMAND_ENVELOPE_ID = "11111111-1111-1111-1111-111111111111"
        const val COMMAND_ID = "22222222-2222-2222-2222-222222222222"
        const val ACTION_ID = "33333333-3333-3333-3333-333333333333"
        const val STREAM_ID = "44444444-4444-4444-4444-444444444444"
        const val ACKNOWLEDGED_SNAPSHOT_ID = "55555555-5555-5555-5555-555555555555"
        const val FRESH_SNAPSHOT_ID = "66666666-6666-6666-6666-666666666666"
        const val TARGET_PACKAGE = "com.example.target"
    }
}
