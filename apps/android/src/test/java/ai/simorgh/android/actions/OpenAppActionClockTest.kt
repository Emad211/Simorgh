package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.accessibility.AcknowledgedAccessibilityObservation
import ai.simorgh.android.time.CoreClock
import ai.simorgh.android.time.CoreClockEstimator
import ai.simorgh.android.time.CoreClockReading
import ai.simorgh.android.time.CoreDeadlineBudget
import ai.simorgh.android.time.CoreDeadlineUnavailableReason
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

class OpenAppActionClockTest {
    @Test
    fun `observation freshness ignores raw device wall clock metadata`() {
        val clock = MutableCoreClock(
            elapsedMs = 5_000,
            reading = reading(
                generation = 1,
                observedAtElapsedMs = 5_000,
                estimatedCoreMs = 10_000,
                uncertaintyMs = 0,
            ),
        )
        val beforeSnapshot = snapshot(
            id = BEFORE_SNAPSHOT_ID,
            capturedAtMs = 900_000,
            capturedAtElapsedMs = 4_500,
            activePackage = SOURCE_PACKAGE,
        )
        val before = acknowledged(1, beforeSnapshot)
        val fresh = beforeSnapshot.copy(
            snapshotId = FRESH_SNAPSHOT_ID,
            capturedAtMs = 10,
            capturedAtElapsedRealtimeMs = 5_100,
        )
        val afterSnapshot = snapshot(
            id = AFTER_SNAPSHOT_ID,
            capturedAtMs = 1,
            capturedAtElapsedMs = 5_200,
            activePackage = TARGET_PACKAGE,
        )
        val verification = policy()
        val evidence = CallbackEvidenceSource(
            latest = before,
            fresh = fresh,
            post = PostActionEvidenceResult(
                status = PostActionEvidenceStatus.SATISFIED,
                observation = acknowledged(2, afterSnapshot),
                evaluation = UiPostconditionEvaluator.evaluate(afterSnapshot, verification),
                detail = "monotonic fixture verified",
            ),
            onFresh = { clock.elapsedMs = 5_100 },
            onPostWait = { clock.elapsedMs = 5_200 },
        )

        val result = execute(
            command = command(policy = verification),
            clock = clock,
            evidence = evidence,
            launcher = OpenAppLauncher { acceptedLaunch() },
        )

        assertEquals(ActionOutcome.SUCCEEDED, result.outcome)
        assertEquals(ActionFailureCode.NONE, result.failureCode)
        assertEquals(200, result.finishedAtMs - result.startedAtMs)
    }

    @Test
    fun `unavailable Core clock blocks before evidence access or launch`() {
        val clock = MutableCoreClock(elapsedMs = 5_000, reading = null)
        val evidence = CallbackEvidenceSource()
        val launchCount = AtomicInteger(0)

        val result = execute(
            command = command(),
            clock = clock,
            evidence = evidence,
            launcher = OpenAppLauncher {
                launchCount.incrementAndGet()
                acceptedLaunch()
            },
        )

        assertEquals(ActionOutcome.BLOCKED, result.outcome)
        assertEquals(ActionFailureCode.PRECONDITION_FAILED, result.failureCode)
        assertEquals(0, result.attempts)
        assertEquals(0, evidence.latestCalls)
        assertEquals(0, launchCount.get())
        assertTrue(result.detail.contains("Core clock"))
    }

    @Test
    fun `clock generation change at immediate launch boundary prevents side effect`() {
        val clock = MutableCoreClock(
            elapsedMs = 5_000,
            reading = reading(1, 5_000, 10_000, 0),
        )
        val beforeSnapshot = snapshot(
            id = BEFORE_SNAPSHOT_ID,
            capturedAtMs = 10_000,
            capturedAtElapsedMs = 4_500,
            activePackage = SOURCE_PACKAGE,
        )
        val before = acknowledged(1, beforeSnapshot)
        val fresh = beforeSnapshot.copy(
            snapshotId = FRESH_SNAPSHOT_ID,
            capturedAtElapsedRealtimeMs = 5_050,
        )
        val evidence = CallbackEvidenceSource(
            latest = before,
            fresh = fresh,
            onFresh = {
                clock.elapsedMs = 5_050
                clock.reading = reading(2, 5_050, 10_050, 0)
            },
        )
        val launchCount = AtomicInteger(0)

        val result = execute(
            command = command(),
            clock = clock,
            evidence = evidence,
            launcher = OpenAppLauncher {
                launchCount.incrementAndGet()
                acceptedLaunch()
            },
        )

        assertEquals(ActionOutcome.BLOCKED, result.outcome)
        assertEquals(ActionFailureCode.PRECONDITION_FAILED, result.failureCode)
        assertEquals(0, result.attempts)
        assertEquals(0, launchCount.get())
        assertTrue(result.detail.contains("generation"))
    }

    @Test
    fun `device wall clock jump during execution does not alter result duration`() {
        val clocks = MutableClocks(
            elapsedMs = 5_000,
            wallMs = 100_000,
        )
        val estimator = CoreClockEstimator(
            monotonicMillis = { clocks.elapsedMs },
            wallClockMillis = { clocks.wallMs },
            maximumEstimateAgeMs = 10_000,
        )
        estimator.beginGeneration(7)
        estimator.recordSample(
            sampleGeneration = 7,
            requestSentElapsedMs = 4_980,
            responseReceivedElapsedMs = 5_000,
            serverTimeMs = 10_000,
            responseReceivedWallClockMs = clocks.wallMs,
        )

        val beforeSnapshot = snapshot(
            id = BEFORE_SNAPSHOT_ID,
            capturedAtMs = 100_000,
            capturedAtElapsedMs = 4_500,
            activePackage = SOURCE_PACKAGE,
        )
        val before = acknowledged(1, beforeSnapshot)
        val fresh = beforeSnapshot.copy(
            snapshotId = FRESH_SNAPSHOT_ID,
            capturedAtMs = 900_000,
            capturedAtElapsedRealtimeMs = 5_100,
        )
        val afterSnapshot = snapshot(
            id = AFTER_SNAPSHOT_ID,
            capturedAtMs = 10,
            capturedAtElapsedMs = 5_200,
            activePackage = TARGET_PACKAGE,
        )
        val verification = policy()
        val evidence = CallbackEvidenceSource(
            latest = before,
            fresh = fresh,
            post = PostActionEvidenceResult(
                status = PostActionEvidenceStatus.SATISFIED,
                observation = acknowledged(2, afterSnapshot),
                evaluation = UiPostconditionEvaluator.evaluate(afterSnapshot, verification),
                detail = "wall jump fixture verified",
            ),
            onFresh = {
                clocks.elapsedMs = 5_100
                clocks.wallMs = 900_000
            },
            onPostWait = {
                clocks.elapsedMs = 5_200
                clocks.wallMs = 25
            },
        )

        val result = execute(
            command = command(policy = verification),
            clock = estimator,
            evidence = evidence,
            launcher = OpenAppLauncher { acceptedLaunch() },
        )

        assertEquals(ActionOutcome.SUCCEEDED, result.outcome)
        assertEquals(200, result.finishedAtMs - result.startedAtMs)
    }

    private fun execute(
        command: AndroidActionCommand,
        clock: CoreClock,
        evidence: CallbackEvidenceSource,
        launcher: OpenAppLauncher,
    ): AndroidActionResult {
        val completed = CountDownLatch(1)
        val result = AtomicReference<AndroidActionResult?>()
        val executor = OpenAppActionExecutor(
            launcher = launcher,
            evidenceSource = evidence,
            coreClock = clock,
        )
        try {
            assertTrue(
                executor.submit(
                    ReceivedAndroidAction(COMMAND_ENVELOPE_ID, command),
                    AndroidActionCompletion { value ->
                        result.set(value)
                        completed.countDown()
                    },
                ),
            )
            assertTrue(completed.await(2, TimeUnit.SECONDS))
            return requireNotNull(result.get())
        } finally {
            executor.close()
        }
    }

    private fun command(
        policy: AndroidVerificationPolicy = policy(),
    ): AndroidActionCommand = AndroidActionContractValidator.validate(
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
            verification = policy,
        ),
    )

    private fun policy(): AndroidVerificationPolicy = AndroidVerificationPolicy(
        predicates = listOf(ActivePackageEqualsPredicate(TARGET_PACKAGE)),
        timeoutMs = 1_000,
        stableSamples = 1,
    )

    private fun snapshot(
        id: String,
        capturedAtMs: Long,
        capturedAtElapsedMs: Long,
        activePackage: String,
    ): AccessibilitySnapshot = AccessibilitySnapshot(
        snapshotId = id,
        capturedAtMs = capturedAtMs,
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
        acknowledgedAtMs = 10_000,
    )

    private fun reading(
        generation: Long,
        observedAtElapsedMs: Long,
        estimatedCoreMs: Long,
        uncertaintyMs: Long,
    ): CoreClockReading = CoreClockReading(
        generation = generation,
        estimatedCoreTimeMs = estimatedCoreMs,
        earliestCoreTimeMs = estimatedCoreMs - uncertaintyMs,
        latestCoreTimeMs = estimatedCoreMs + uncertaintyMs,
        uncertaintyMs = uncertaintyMs,
        sampleAgeMs = 0,
        lastRoundTripTimeMs = uncertaintyMs * 2,
        sampleCount = 1,
        discontinuityCount = 0,
        wallClockJumpCount = 0,
        observedAtElapsedRealtimeMs = observedAtElapsedMs,
    )

    private fun acceptedLaunch(): OpenAppLaunchAttempt = OpenAppLaunchAttempt(
        status = OpenAppLaunchStatus.ACCEPTED,
        adapter = "clock_fixture",
        detail = "accepted",
    )

    private class MutableCoreClock(
        var elapsedMs: Long,
        var reading: CoreClockReading?,
    ) : CoreClock {
        override fun elapsedRealtimeMs(): Long = elapsedMs

        override fun reading(): CoreClockReading? = reading

        override fun deadlineBudget(deadlineCoreTimeMs: Long): CoreDeadlineBudget {
            val current = reading
                ?: return CoreDeadlineBudget.Unavailable(
                    kind = CoreDeadlineUnavailableReason.CLOCK_UNAVAILABLE,
                    reason = "fixture clock unavailable",
                )
            val centered = deadlineCoreTimeMs - current.estimatedCoreTimeMs
            if (centered <= current.uncertaintyMs) {
                return CoreDeadlineBudget.Unavailable(
                    kind = CoreDeadlineUnavailableReason.UNCERTAINTY,
                    reason = "fixture uncertainty consumes deadline",
                    reading = current,
                )
            }
            val guaranteed = deadlineCoreTimeMs - current.latestCoreTimeMs
            return if (guaranteed > 0) {
                CoreDeadlineBudget.Available(guaranteed, current)
            } else {
                CoreDeadlineBudget.Unavailable(
                    kind = CoreDeadlineUnavailableReason.EXPIRED,
                    reason = "fixture deadline elapsed",
                    reading = current,
                )
            }
        }
    }

    private class CallbackEvidenceSource(
        private val latest: AcknowledgedAccessibilityObservation? = null,
        private val fresh: AccessibilitySnapshot? = null,
        private val post: PostActionEvidenceResult = PostActionEvidenceResult(
            status = PostActionEvidenceStatus.OBSERVATION_TIMEOUT,
        ),
        private val onFresh: () -> Unit = {},
        private val onPostWait: () -> Unit = {},
    ) : OpenAppEvidenceSource {
        var latestCalls: Int = 0
            private set

        override fun latestAcknowledged(): AcknowledgedAccessibilityObservation? {
            latestCalls += 1
            return latest
        }

        override fun requestFreshLocalSnapshot(
            timeoutMillis: Long,
            cancelled: () -> Boolean,
        ): AccessibilitySnapshot? {
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
            onPostWait()
            return post
        }

        override fun close() = Unit
    }

    private data class MutableClocks(
        var elapsedMs: Long,
        var wallMs: Long,
    )

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
