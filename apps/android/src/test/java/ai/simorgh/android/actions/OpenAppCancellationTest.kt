package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.accessibility.AcknowledgedAccessibilityObservation
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class OpenAppCancellationTest {
    @Test
    fun `cancellation while waiting for fresh pre-launch evidence has zero attempts`() {
        val evidence = BlockingPreLaunchEvidenceSource(acknowledged())
        val result = AtomicReference<AndroidActionResult?>()
        val completed = CountDownLatch(1)
        val executor = OpenAppActionExecutor(
            launcher = OpenAppLauncher { error("launcher must not be called") },
            evidenceSource = evidence,
            wallClockMillis = { NOW_MS },
        )
        try {
            assertTrue(submit(executor, result, completed))
            assertTrue(evidence.captureStarted.await(1, TimeUnit.SECONDS))
            assertTrue(executor.cancel(COMMAND_ID, ACTION_ID, "fixture cancel"))
            evidence.releaseCapture.countDown()
            assertTrue(completed.await(2, TimeUnit.SECONDS))

            val cancelled = requireNotNull(result.get())
            assertEquals(ActionOutcome.CANCELLED, cancelled.outcome)
            assertEquals(ActionFailureCode.CANCELLED, cancelled.failureCode)
            assertEquals(0, cancelled.attempts)
        } finally {
            evidence.releaseCapture.countDown()
            executor.close()
        }
    }

    @Test
    fun `cancellation after launch acceptance records one attempt and no rollback claim`() {
        val evidence = BlockingPostLaunchEvidenceSource(
            acknowledged = acknowledged(),
            fresh = freshSnapshot(),
        )
        val result = AtomicReference<AndroidActionResult?>()
        val completed = CountDownLatch(1)
        val launchAccepted = CountDownLatch(1)
        val executor = OpenAppActionExecutor(
            launcher = OpenAppLauncher {
                launchAccepted.countDown()
                OpenAppLaunchAttempt(
                    status = OpenAppLaunchStatus.ACCEPTED,
                    adapter = "fixture",
                    detail = "accepted",
                )
            },
            evidenceSource = evidence,
            wallClockMillis = { NOW_MS },
        )
        try {
            assertTrue(submit(executor, result, completed))
            assertTrue(launchAccepted.await(1, TimeUnit.SECONDS))
            assertTrue(evidence.postWaitStarted.await(1, TimeUnit.SECONDS))
            assertTrue(executor.cancel(COMMAND_ID, ACTION_ID, "fixture cancel"))
            evidence.releasePostWait.countDown()
            assertTrue(completed.await(2, TimeUnit.SECONDS))

            val cancelled = requireNotNull(result.get())
            assertEquals(ActionOutcome.CANCELLED, cancelled.outcome)
            assertEquals(ActionFailureCode.CANCELLED, cancelled.failureCode)
            assertEquals(1, cancelled.attempts)
            assertTrue(cancelled.detail.contains("cancelled"))
        } finally {
            evidence.releasePostWait.countDown()
            executor.close()
        }
    }

    private fun submit(
        executor: OpenAppActionExecutor,
        result: AtomicReference<AndroidActionResult?>,
        completed: CountDownLatch,
    ): Boolean = executor.submit(
        request = ReceivedAndroidAction(COMMAND_ENVELOPE_ID, command()),
        completion = AndroidActionCompletion { value ->
            result.set(value)
            completed.countDown()
        },
    )

    private fun command(): AndroidActionCommand = AndroidActionContractValidator.validate(
        AndroidActionCommand(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            issuedAtMs = NOW_MS - 1_000,
            deadlineAtMs = NOW_MS + 10_000,
            precondition = ObservationPrecondition(
                expectedStreamId = STREAM_ID,
                expectedActivePackage = SOURCE_PACKAGE,
                maximumAgeMs = 2_000,
            ),
            operation = OpenAppOperation(packageName = TARGET_PACKAGE),
            verification = AndroidVerificationPolicy(
                predicates = listOf(ActivePackageEqualsPredicate(TARGET_PACKAGE)),
                timeoutMs = 1_000,
            ),
        ),
    )

    private fun acknowledged(): AcknowledgedAccessibilityObservation {
        val snapshot = sourceSnapshot()
        return AcknowledgedAccessibilityObservation(
            streamId = STREAM_ID,
            sequence = 1,
            stateFingerprint = AccessibilitySnapshotFingerprint.calculate(snapshot),
            snapshot = snapshot,
            acknowledgedAtMs = 9_510,
        )
    }

    private fun sourceSnapshot(): AccessibilitySnapshot = AccessibilitySnapshot(
        snapshotId = SOURCE_SNAPSHOT_ID,
        capturedAtMs = 9_500,
        activePackage = SOURCE_PACKAGE,
        activeWindowId = 1,
        windows = emptyList(),
        nodes = emptyList(),
        truncated = false,
        truncationReasons = emptyList(),
        maxDepthObserved = 0,
    )

    private fun freshSnapshot(): AccessibilitySnapshot = sourceSnapshot().copy(
        snapshotId = FRESH_SNAPSHOT_ID,
        capturedAtMs = NOW_MS,
    )

    private class BlockingPreLaunchEvidenceSource(
        private val acknowledged: AcknowledgedAccessibilityObservation,
    ) : OpenAppEvidenceSource {
        val captureStarted = CountDownLatch(1)
        val releaseCapture = CountDownLatch(1)

        override fun latestAcknowledged(): AcknowledgedAccessibilityObservation = acknowledged

        override fun requestFreshLocalSnapshot(
            timeoutMillis: Long,
            cancelled: () -> Boolean,
        ): AccessibilitySnapshot? {
            captureStarted.countDown()
            releaseCapture.await(1, TimeUnit.SECONDS)
            return null
        }

        override fun awaitVerifiedObservation(
            before: AcknowledgedAccessibilityObservation,
            launchedAtMs: Long,
            policy: AndroidVerificationPolicy,
            timeoutMillis: Long,
            cancelled: () -> Boolean,
        ): PostActionEvidenceResult = error("post wait must not start")

        override fun close() {
            releaseCapture.countDown()
        }
    }

    private class BlockingPostLaunchEvidenceSource(
        private val acknowledged: AcknowledgedAccessibilityObservation,
        private val fresh: AccessibilitySnapshot,
    ) : OpenAppEvidenceSource {
        val postWaitStarted = CountDownLatch(1)
        val releasePostWait = CountDownLatch(1)

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
            postWaitStarted.countDown()
            releasePostWait.await(1, TimeUnit.SECONDS)
            return PostActionEvidenceResult(
                status = if (cancelled()) {
                    PostActionEvidenceStatus.CANCELLED
                } else {
                    PostActionEvidenceStatus.OBSERVATION_TIMEOUT
                },
                detail = "action was cancelled while waiting for post-action evidence",
            )
        }

        override fun close() {
            releasePostWait.countDown()
        }
    }

    private companion object {
        const val NOW_MS = 10_000L
        const val COMMAND_ENVELOPE_ID = "11111111-1111-1111-1111-111111111111"
        const val COMMAND_ID = "22222222-2222-2222-2222-222222222222"
        const val ACTION_ID = "33333333-3333-3333-3333-333333333333"
        const val STREAM_ID = "44444444-4444-4444-4444-444444444444"
        const val SOURCE_SNAPSHOT_ID = "55555555-5555-5555-5555-555555555555"
        const val FRESH_SNAPSHOT_ID = "66666666-6666-6666-6666-666666666666"
        const val SOURCE_PACKAGE = "com.android.launcher"
        const val TARGET_PACKAGE = "com.example.target"
    }
}
