package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilityNodeSnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.accessibility.AcknowledgedAccessibilityObservation
import ai.simorgh.android.accessibility.ScreenBounds
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

class OpenAppDeepLinkExecutionTest {
    @Test
    fun `explicit URI launches even when declared destination already appears satisfied`() {
        val beforeSnapshot = snapshot(
            id = BEFORE_SNAPSHOT_ID,
            capturedAtMs = NOW_MS - 500,
        )
        val before = acknowledged(sequence = 4, snapshot = beforeSnapshot)
        val fresh = beforeSnapshot.copy(
            snapshotId = FRESH_SNAPSHOT_ID,
            capturedAtMs = NOW_MS,
        )
        val afterSnapshot = beforeSnapshot.copy(
            snapshotId = AFTER_SNAPSHOT_ID,
            capturedAtMs = NOW_MS + 100,
        )
        val after = acknowledged(sequence = 5, snapshot = afterSnapshot)
        val policy = verificationPolicy()
        val evidence = FakeEvidenceSource(
            latest = before,
            fresh = fresh,
            postResult = PostActionEvidenceResult(
                status = PostActionEvidenceStatus.SATISFIED,
                observation = after,
                evaluation = UiPostconditionEvaluator.evaluate(afterSnapshot, policy),
                detail = "deep-link destination verified",
            ),
        )
        val launchCount = AtomicInteger(0)
        val launcher = OpenAppLauncher { operation ->
            assertEquals(TARGET_URI, operation.uri)
            launchCount.incrementAndGet()
            OpenAppLaunchAttempt(
                status = OpenAppLaunchStatus.ACCEPTED,
                adapter = "fixture_uri",
                detail = "accepted",
            )
        }
        val completed = CountDownLatch(1)
        val completion = AtomicReference<AndroidActionResult?>()
        val executor = OpenAppActionExecutor(
            launcher = launcher,
            evidenceSource = evidence,
            wallClockMillis = { NOW_MS },
        )

        try {
            assertTrue(
                executor.submit(
                    ReceivedAndroidAction(COMMAND_ENVELOPE_ID, command(policy)),
                    AndroidActionCompletion { result ->
                        completion.set(result)
                        completed.countDown()
                    },
                ),
            )
            assertTrue(completed.await(2, TimeUnit.SECONDS))

            val result = requireNotNull(completion.get())
            assertEquals(ActionOutcome.SUCCEEDED, result.outcome)
            assertEquals(ActionFailureCode.NONE, result.failureCode)
            assertEquals(1, result.attempts)
            assertEquals(1, launchCount.get())
            assertEquals(AFTER_SNAPSHOT_ID, result.afterObservation?.snapshotId)
            assertTrue(result.detail.contains("deep-link destination verified"))
        } finally {
            executor.close()
        }
    }

    private fun command(policy: AndroidVerificationPolicy): AndroidActionCommand =
        AndroidActionContractValidator.validate(
            AndroidActionCommand(
                commandId = COMMAND_ID,
                actionId = ACTION_ID,
                issuedAtMs = NOW_MS - 1_000,
                deadlineAtMs = NOW_MS + 10_000,
                precondition = ObservationPrecondition(
                    expectedStreamId = STREAM_ID,
                    minimumSequence = 4,
                    expectedStateFingerprint = AccessibilitySnapshotFingerprint.calculate(
                        snapshot(BEFORE_SNAPSHOT_ID, NOW_MS - 500),
                    ),
                    expectedActivePackage = TARGET_PACKAGE,
                    maximumAgeMs = 2_000,
                ),
                operation = OpenAppOperation(
                    packageName = TARGET_PACKAGE,
                    uri = TARGET_URI,
                ),
                verification = policy,
            ),
        )

    private fun verificationPolicy(): AndroidVerificationPolicy = AndroidVerificationPolicy(
        predicates = listOf(
            ActivePackageEqualsPredicate(TARGET_PACKAGE),
            NodeExistsPredicate(
                AndroidNodeSelector(
                    packageName = TARGET_PACKAGE,
                    viewId = TARGET_VIEW_ID,
                    requiredFields = setOf(SelectorField.VIEW_ID),
                ),
            ),
        ),
        timeoutMs = 1_000,
        stableSamples = 1,
    )

    private fun snapshot(id: String, capturedAtMs: Long): AccessibilitySnapshot {
        val node = AccessibilityNodeSnapshot(
            nodeId = NODE_ID,
            path = "0",
            depth = 0,
            windowId = 1,
            packageName = TARGET_PACKAGE,
            className = "android.widget.TextView",
            viewId = TARGET_VIEW_ID,
            text = "جزئیات آیتم ۴۲",
            bounds = ScreenBounds(0, 0, 500, 200),
            semanticFingerprint = SEMANTIC_FINGERPRINT,
            childCount = 0,
            inputType = 0,
            clickable = false,
            longClickable = false,
            focusable = false,
            focused = false,
            editable = false,
            scrollable = false,
            enabled = true,
            selected = false,
            checkable = false,
            checked = false,
            visibleToUser = true,
            accessibilityFocused = false,
            password = false,
            heading = true,
            actions = emptyList(),
        )
        return AccessibilitySnapshot(
            snapshotId = id,
            capturedAtMs = capturedAtMs,
            activePackage = TARGET_PACKAGE,
            activeWindowId = 1,
            rootNodeId = node.nodeId,
            windows = emptyList(),
            nodes = listOf(node),
            truncated = false,
            truncationReasons = emptyList(),
            maxDepthObserved = 0,
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
        acknowledgedAtMs = snapshot.capturedAtMs + 1,
    )

    private class FakeEvidenceSource(
        private val latest: AcknowledgedAccessibilityObservation,
        private val fresh: AccessibilitySnapshot,
        private val postResult: PostActionEvidenceResult,
    ) : OpenAppEvidenceSource {
        override fun latestAcknowledged(): AcknowledgedAccessibilityObservation = latest

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
        ): PostActionEvidenceResult = postResult

        override fun close() = Unit
    }

    private companion object {
        const val NOW_MS = 10_000L
        const val STREAM_ID = "11111111-1111-1111-1111-111111111111"
        const val COMMAND_ENVELOPE_ID = "22222222-2222-2222-2222-222222222222"
        const val COMMAND_ID = "33333333-3333-3333-3333-333333333333"
        const val ACTION_ID = "44444444-4444-4444-4444-444444444444"
        const val BEFORE_SNAPSHOT_ID = "55555555-5555-5555-5555-555555555555"
        const val FRESH_SNAPSHOT_ID = "66666666-6666-6666-6666-666666666666"
        const val AFTER_SNAPSHOT_ID = "77777777-7777-7777-7777-777777777777"
        const val TARGET_PACKAGE = "com.example.target"
        const val TARGET_URI = "example://items/42"
        const val TARGET_VIEW_ID = "com.example.target:id/item_42"
        const val NODE_ID = "aaaaaaaaaaaaaaaaaaaaaaaa"
        const val SEMANTIC_FINGERPRINT = "bbbbbbbbbbbbbbbbbbbbbbbb"
    }
}
