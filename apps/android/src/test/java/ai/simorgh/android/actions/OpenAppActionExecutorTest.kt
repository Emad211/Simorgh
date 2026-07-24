package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.accessibility.AcknowledgedAccessibilityObservation
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

class OpenAppActionExecutorTest {
    @Test
    fun `successful open app requires fresh matching precondition and Core-acked postcondition`() {
        val beforeSnapshot = snapshot(
            id = BEFORE_SNAPSHOT_ID,
            capturedAtMs = 9_500,
            activePackage = SOURCE_PACKAGE,
        )
        val before = acknowledged(sequence = 7, snapshot = beforeSnapshot)
        val freshBefore = beforeSnapshot.copy(
            snapshotId = FRESH_BEFORE_SNAPSHOT_ID,
            capturedAtMs = NOW_MS,
        )
        val afterSnapshot = snapshot(
            id = AFTER_SNAPSHOT_ID,
            capturedAtMs = NOW_MS + 100,
            activePackage = TARGET_PACKAGE,
        )
        val after = acknowledged(sequence = 8, snapshot = afterSnapshot)
        val policy = verificationPolicy()
        val evidence = FakeEvidenceSource(
            latest = before,
            fresh = freshBefore,
            postResult = PostActionEvidenceResult(
                status = PostActionEvidenceStatus.SATISFIED,
                observation = after,
                evaluation = UiPostconditionEvaluator.evaluate(afterSnapshot, policy),
                detail = "fixture verified",
            ),
        )
        val launchCount = AtomicInteger(0)
        val launcher = OpenAppLauncher {
            launchCount.incrementAndGet()
            OpenAppLaunchAttempt(
                status = OpenAppLaunchStatus.ACCEPTED,
                adapter = "fixture",
                detail = "accepted",
            )
        }

        val result = execute(
            command = command(policy = policy),
            launcher = launcher,
            evidence = evidence,
        )

        assertEquals(ActionOutcome.SUCCEEDED, result.outcome)
        assertEquals(ActionFailureCode.NONE, result.failureCode)
        assertEquals(1, result.attempts)
        assertEquals(1, launchCount.get())
        assertEquals(BEFORE_SNAPSHOT_ID, result.beforeObservation?.snapshotId)
        assertEquals(AFTER_SNAPSHOT_ID, result.afterObservation?.snapshotId)
        assertEquals(PredicateOutcome.SATISFIED, result.predicates.single().outcome)
        assertTrue(result.detail.contains("fixture verified"))
    }

    @Test
    fun `stale acknowledged observation blocks before fresh capture or launch`() {
        val stale = acknowledged(
            sequence = 2,
            snapshot = snapshot(
                id = BEFORE_SNAPSHOT_ID,
                capturedAtMs = 1_000,
                activePackage = SOURCE_PACKAGE,
            ),
        )
        val evidence = FakeEvidenceSource(latest = stale)
        val launchCount = AtomicInteger(0)

        val result = execute(
            command = command(maximumAgeMs = 2_000),
            launcher = OpenAppLauncher {
                launchCount.incrementAndGet()
                acceptedLaunch()
            },
            evidence = evidence,
        )

        assertEquals(ActionOutcome.BLOCKED, result.outcome)
        assertEquals(ActionFailureCode.PRECONDITION_FAILED, result.failureCode)
        assertEquals(0, result.attempts)
        assertEquals(0, launchCount.get())
        assertEquals(0, evidence.freshRequestCount)
    }

    @Test
    fun `UI change after Core acknowledgement fails TOCTOU guard`() {
        val before = acknowledged(
            sequence = 3,
            snapshot = snapshot(
                id = BEFORE_SNAPSHOT_ID,
                capturedAtMs = 9_500,
                activePackage = SOURCE_PACKAGE,
            ),
        )
        val changed = snapshot(
            id = FRESH_BEFORE_SNAPSHOT_ID,
            capturedAtMs = NOW_MS,
            activePackage = OTHER_PACKAGE,
        )
        val evidence = FakeEvidenceSource(latest = before, fresh = changed)
        val launchCount = AtomicInteger(0)

        val result = execute(
            command = command(),
            launcher = OpenAppLauncher {
                launchCount.incrementAndGet()
                acceptedLaunch()
            },
            evidence = evidence,
        )

        assertEquals(ActionOutcome.BLOCKED, result.outcome)
        assertEquals(ActionFailureCode.PRECONDITION_FAILED, result.failureCode)
        assertTrue(result.detail.contains("UI changed"))
        assertEquals(0, launchCount.get())
    }

    @Test
    fun `Core evidence invalidated after fresh capture blocks at the launch boundary`() {
        val beforeSnapshot = snapshot(
            id = BEFORE_SNAPSHOT_ID,
            capturedAtMs = 9_500,
            activePackage = SOURCE_PACKAGE,
        )
        val before = acknowledged(sequence = 3, snapshot = beforeSnapshot)
        val fresh = beforeSnapshot.copy(
            snapshotId = FRESH_BEFORE_SNAPSHOT_ID,
            capturedAtMs = NOW_MS,
        )
        val latestCalls = AtomicInteger(0)
        val evidence = FakeEvidenceSource(
            latestProvider = {
                if (latestCalls.getAndIncrement() == 0) before else null
            },
            fresh = fresh,
        )
        val launchCount = AtomicInteger(0)

        val result = execute(
            command = command(),
            launcher = OpenAppLauncher {
                launchCount.incrementAndGet()
                acceptedLaunch()
            },
            evidence = evidence,
        )

        assertEquals(ActionOutcome.BLOCKED, result.outcome)
        assertEquals(ActionFailureCode.PRECONDITION_FAILED, result.failureCode)
        assertEquals(0, result.attempts)
        assertEquals(0, launchCount.get())
        assertEquals(2, evidence.latestRequestCount)
        assertTrue(result.detail.contains("invalidated"))
    }

    @Test
    fun `background launch guard becomes unsupported capability rather than false success`() {
        val before = freshBeforeEvidence()
        val evidence = FakeEvidenceSource(
            latest = before.first,
            fresh = before.second,
        )

        val result = execute(
            command = command(),
            launcher = OpenAppLauncher {
                OpenAppLaunchAttempt(
                    status = OpenAppLaunchStatus.BACKGROUND_START_BLOCKED,
                    adapter = "background_launch_guard",
                    detail = "overlay access is missing",
                )
            },
            evidence = evidence,
        )

        assertEquals(ActionOutcome.BLOCKED, result.outcome)
        assertEquals(ActionFailureCode.UNSUPPORTED_CAPABILITY, result.failureCode)
        assertNull(result.afterObservation)
        assertTrue(result.detail.contains("overlay access"))
    }

    @Test
    fun `missing target package is a typed failure and is never verified`() {
        val before = freshBeforeEvidence()
        val evidence = FakeEvidenceSource(
            latest = before.first,
            fresh = before.second,
        )

        val result = execute(
            command = command(),
            launcher = OpenAppLauncher {
                OpenAppLaunchAttempt(
                    status = OpenAppLaunchStatus.TARGET_NOT_FOUND,
                    adapter = "fixture",
                    detail = "package not found",
                )
            },
            evidence = evidence,
        )

        assertEquals(ActionOutcome.FAILED, result.outcome)
        assertEquals(ActionFailureCode.TARGET_NOT_FOUND, result.failureCode)
        assertEquals(0, evidence.postWaitCount)
    }

    @Test
    fun `accepted launch without post observation times out instead of succeeding`() {
        val before = freshBeforeEvidence()
        val evidence = FakeEvidenceSource(
            latest = before.first,
            fresh = before.second,
            postResult = PostActionEvidenceResult(
                status = PostActionEvidenceStatus.OBSERVATION_TIMEOUT,
                detail = "no post-launch snapshot",
            ),
        )

        val result = execute(
            command = command(),
            launcher = OpenAppLauncher { acceptedLaunch() },
            evidence = evidence,
        )

        assertEquals(ActionOutcome.TIMED_OUT, result.outcome)
        assertEquals(ActionFailureCode.OBSERVATION_TIMEOUT, result.failureCode)
        assertEquals(1, result.attempts)
        assertNull(result.afterObservation)
    }

    @Test
    fun `non-open-app operation is rejected before executor ownership`() {
        val evidence = FakeEvidenceSource()
        val executor = OpenAppActionExecutor(
            launcher = OpenAppLauncher { acceptedLaunch() },
            evidenceSource = evidence,
            wallClockMillis = { NOW_MS },
        )
        val completion = AtomicReference<AndroidActionResult?>()
        val command = AndroidActionContractValidator.validate(
            AndroidActionCommand(
                commandId = COMMAND_ID,
                actionId = ACTION_ID,
                issuedAtMs = NOW_MS - 1_000,
                deadlineAtMs = NOW_MS + 10_000,
                precondition = ObservationPrecondition(),
                operation = WaitOperation(durationMs = 100),
                verification = verificationPolicy(),
            ),
        )

        val accepted = executor.submit(
            ReceivedAndroidAction(COMMAND_ENVELOPE_ID, command),
            AndroidActionCompletion(completion::set),
        )

        assertFalse(accepted)
        assertNull(completion.get())
        executor.close()
    }

    private fun execute(
        command: AndroidActionCommand,
        launcher: OpenAppLauncher,
        evidence: FakeEvidenceSource,
    ): AndroidActionResult {
        val completion = AtomicReference<AndroidActionResult?>()
        val completed = CountDownLatch(1)
        val executor = OpenAppActionExecutor(
            launcher = launcher,
            evidenceSource = evidence,
            wallClockMillis = { NOW_MS },
        )
        try {
            assertTrue(
                executor.submit(
                    ReceivedAndroidAction(COMMAND_ENVELOPE_ID, command),
                    AndroidActionCompletion { result ->
                        completion.set(result)
                        completed.countDown()
                    },
                ),
            )
            assertTrue(completed.await(2, TimeUnit.SECONDS))
            return requireNotNull(completion.get())
        } finally {
            executor.close()
        }
    }

    private fun command(
        policy: AndroidVerificationPolicy = verificationPolicy(),
        maximumAgeMs: Long = 2_000,
    ): AndroidActionCommand = AndroidActionContractValidator.validate(
        AndroidActionCommand(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            issuedAtMs = NOW_MS - 1_000,
            deadlineAtMs = NOW_MS + 10_000,
            precondition = ObservationPrecondition(
                expectedStreamId = STREAM_ID,
                minimumSequence = 1,
                expectedActivePackage = SOURCE_PACKAGE,
                maximumAgeMs = maximumAgeMs,
            ),
            operation = OpenAppOperation(packageName = TARGET_PACKAGE),
            verification = policy,
        ),
    )

    private fun verificationPolicy(): AndroidVerificationPolicy = AndroidVerificationPolicy(
        predicates = listOf(ActivePackageEqualsPredicate(TARGET_PACKAGE)),
        timeoutMs = 1_000,
        stableSamples = 1,
    )

    private fun freshBeforeEvidence(): Pair<AcknowledgedAccessibilityObservation, AccessibilitySnapshot> {
        val beforeSnapshot = snapshot(
            id = BEFORE_SNAPSHOT_ID,
            capturedAtMs = 9_500,
            activePackage = SOURCE_PACKAGE,
        )
        val acknowledged = acknowledged(
            sequence = 1,
            snapshot = beforeSnapshot,
        )
        return acknowledged to beforeSnapshot.copy(
            snapshotId = FRESH_BEFORE_SNAPSHOT_ID,
            capturedAtMs = NOW_MS,
        )
    }

    private fun acknowledged(
        sequence: Long,
        snapshot: AccessibilitySnapshot,
    ): AcknowledgedAccessibilityObservation = AcknowledgedAccessibilityObservation(
        streamId = STREAM_ID,
        sequence = sequence,
        stateFingerprint = AccessibilitySnapshotFingerprint.calculate(snapshot),
        snapshot = snapshot,
        acknowledgedAtMs = snapshot.capturedAtMs + 10,
    )

    private fun snapshot(
        id: String,
        capturedAtMs: Long,
        activePackage: String,
    ): AccessibilitySnapshot = AccessibilitySnapshot(
        snapshotId = id,
        capturedAtMs = capturedAtMs,
        activePackage = activePackage,
        activeWindowId = 1,
        windows = emptyList(),
        nodes = emptyList(),
        truncated = false,
        truncationReasons = emptyList(),
        maxDepthObserved = 0,
    )

    private fun acceptedLaunch(): OpenAppLaunchAttempt = OpenAppLaunchAttempt(
        status = OpenAppLaunchStatus.ACCEPTED,
        adapter = "fixture",
        detail = "accepted",
    )

    private class FakeEvidenceSource(
        private val latest: AcknowledgedAccessibilityObservation? = null,
        private val latestProvider: (() -> AcknowledgedAccessibilityObservation?)? = null,
        private val fresh: AccessibilitySnapshot? = null,
        private val postResult: PostActionEvidenceResult = PostActionEvidenceResult(
            status = PostActionEvidenceStatus.OBSERVATION_TIMEOUT,
        ),
    ) : OpenAppEvidenceSource {
        var latestRequestCount: Int = 0
            private set
        var freshRequestCount: Int = 0
            private set
        var postWaitCount: Int = 0
            private set

        override fun latestAcknowledged(): AcknowledgedAccessibilityObservation? {
            latestRequestCount += 1
            return latestProvider?.invoke() ?: latest
        }

        override fun requestFreshLocalSnapshot(
            timeoutMillis: Long,
            cancelled: () -> Boolean,
        ): AccessibilitySnapshot? {
            freshRequestCount += 1
            return fresh
        }

        override fun awaitVerifiedObservation(
            before: AcknowledgedAccessibilityObservation,
            launchedAtMs: Long,
            policy: AndroidVerificationPolicy,
            timeoutMillis: Long,
            cancelled: () -> Boolean,
        ): PostActionEvidenceResult {
            postWaitCount += 1
            return postResult
        }

        override fun close() = Unit
    }

    private companion object {
        const val NOW_MS = 10_000L
        const val SOURCE_PACKAGE = "com.example.source"
        const val TARGET_PACKAGE = "com.example.target"
        const val OTHER_PACKAGE = "com.example.other"
        const val STREAM_ID = "11111111-1111-1111-1111-111111111111"
        const val COMMAND_ENVELOPE_ID = "22222222-2222-2222-2222-222222222222"
        const val COMMAND_ID = "33333333-3333-3333-3333-333333333333"
        const val ACTION_ID = "44444444-4444-4444-4444-444444444444"
        const val BEFORE_SNAPSHOT_ID = "55555555-5555-5555-5555-555555555555"
        const val FRESH_BEFORE_SNAPSHOT_ID = "66666666-6666-6666-6666-666666666666"
        const val AFTER_SNAPSHOT_ID = "77777777-7777-7777-7777-777777777777"
    }
}
