package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilityAcknowledgementBus
import ai.simorgh.android.accessibility.AccessibilityCaptureController
import ai.simorgh.android.accessibility.AccessibilityObservationBus
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.accessibility.AcknowledgedAccessibilityObservation
import java.io.Closeable
import java.util.concurrent.TimeUnit

interface OpenAppEvidenceSource : Closeable {
    fun latestAcknowledged(): AcknowledgedAccessibilityObservation?

    fun requestFreshLocalSnapshot(
        timeoutMillis: Long,
        cancelled: () -> Boolean,
    ): AccessibilitySnapshot?

    fun awaitVerifiedObservation(
        before: AcknowledgedAccessibilityObservation,
        launchedAtMs: Long,
        policy: AndroidVerificationPolicy,
        timeoutMillis: Long,
        cancelled: () -> Boolean,
    ): PostActionEvidenceResult
}

enum class PostActionEvidenceStatus {
    SATISFIED,
    UNSATISFIED,
    INDETERMINATE,
    OBSERVATION_TIMEOUT,
    CANCELLED,
    OBSERVER_UNAVAILABLE,
}

data class PostActionEvidenceResult(
    val status: PostActionEvidenceStatus,
    val observation: AcknowledgedAccessibilityObservation? = null,
    val evaluation: VerificationEvaluation? = null,
    val detail: String = "",
)

class AccessibilityActionEvidenceSource(
    private val captureRequester: () -> Boolean = AccessibilityCaptureController::requestCapture,
    private val wallClockMillis: () -> Long = System::currentTimeMillis,
    private val monotonicNanos: () -> Long = System::nanoTime,
    private val pollIntervalMillis: Long = DEFAULT_POLL_INTERVAL_MILLIS,
) : OpenAppEvidenceSource {
    private val monitor = Object()

    @Volatile
    private var closed = false

    private var latestLocalSnapshot: AccessibilitySnapshot? =
        AccessibilityObservationBus.current().latestSnapshot
    private var latestAcknowledgedObservation: AcknowledgedAccessibilityObservation? =
        AccessibilityAcknowledgementBus.latest()

    private val localSubscription = AccessibilityObservationBus.subscribe { state ->
        synchronized(monitor) {
            latestLocalSnapshot = state.latestSnapshot
            monitor.notifyAll()
        }
    }
    private val acknowledgementSubscription = AccessibilityAcknowledgementBus.subscribe { value ->
        synchronized(monitor) {
            latestAcknowledgedObservation = value
            monitor.notifyAll()
        }
    }

    init {
        require(pollIntervalMillis in 25..1_000) {
            "poll interval must be in 25..1000 milliseconds"
        }
    }

    override fun latestAcknowledged(): AcknowledgedAccessibilityObservation? =
        synchronized(monitor) { latestAcknowledgedObservation }

    override fun requestFreshLocalSnapshot(
        timeoutMillis: Long,
        cancelled: () -> Boolean,
    ): AccessibilitySnapshot? {
        require(timeoutMillis > 0)
        val baselineId = synchronized(monitor) { latestLocalSnapshot?.snapshotId }
        val requestedAtMs = wallClockMillis()
        if (!captureRequester()) {
            return null
        }
        val deadlineNanos = deadlineAfter(timeoutMillis)

        while (!closed && !cancelled()) {
            synchronized(monitor) {
                val candidate = latestLocalSnapshot
                if (
                    candidate != null &&
                    candidate.snapshotId != baselineId &&
                    candidate.capturedAtMs >= requestedAtMs
                ) {
                    return candidate
                }
                val remainingMillis = remainingMillis(deadlineNanos)
                if (remainingMillis <= 0) {
                    return null
                }
                monitor.wait(minOf(remainingMillis, pollIntervalMillis))
            }
        }
        return null
    }

    override fun awaitVerifiedObservation(
        before: AcknowledgedAccessibilityObservation,
        launchedAtMs: Long,
        policy: AndroidVerificationPolicy,
        timeoutMillis: Long,
        cancelled: () -> Boolean,
    ): PostActionEvidenceResult {
        require(timeoutMillis > 0)
        val deadlineNanos = deadlineAfter(timeoutMillis)
        var lastCaptureRequestAtNanos = Long.MIN_VALUE
        var lastProcessedSnapshotId: String? = null
        var stableFingerprint: String? = null
        var stableSamples = 0
        var latestEvaluation: VerificationEvaluation? = null
        var observedPostLaunchSnapshot = false

        while (!closed && !cancelled()) {
            val nowNanos = monotonicNanos()
            if (
                lastCaptureRequestAtNanos == Long.MIN_VALUE ||
                TimeUnit.NANOSECONDS.toMillis(nowNanos - lastCaptureRequestAtNanos) >=
                pollIntervalMillis
            ) {
                captureRequester()
                lastCaptureRequestAtNanos = nowNanos
            }

            val local: AccessibilitySnapshot?
            val acknowledged: AcknowledgedAccessibilityObservation?
            synchronized(monitor) {
                local = latestLocalSnapshot
                acknowledged = latestAcknowledgedObservation
            }

            if (
                local != null &&
                local.snapshotId != lastProcessedSnapshotId &&
                local.snapshotId != before.snapshot.snapshotId &&
                local.capturedAtMs >= launchedAtMs
            ) {
                observedPostLaunchSnapshot = true
                lastProcessedSnapshotId = local.snapshotId
                val evaluation = UiPostconditionEvaluator.evaluate(local, policy)
                latestEvaluation = evaluation
                if (evaluation.outcome == PredicateOutcome.SATISFIED) {
                    val fingerprint = AccessibilitySnapshotFingerprint.calculate(local)
                    if (fingerprint == stableFingerprint) {
                        stableSamples += 1
                    } else {
                        stableFingerprint = fingerprint
                        stableSamples = 1
                    }
                } else {
                    stableFingerprint = null
                    stableSamples = 0
                }
            }

            val qualifyingAcknowledgement = acknowledged?.takeIf { evidence ->
                evidence.snapshot.capturedAtMs >= launchedAtMs &&
                    evidence.snapshot.snapshotId != before.snapshot.snapshotId &&
                    (
                        evidence.streamId != before.streamId ||
                            evidence.sequence > before.sequence
                        ) &&
                    evidence.stateFingerprint == stableFingerprint
            }
            if (
                stableSamples >= policy.stableSamples &&
                qualifyingAcknowledgement != null &&
                latestEvaluation?.outcome == PredicateOutcome.SATISFIED
            ) {
                return PostActionEvidenceResult(
                    status = PostActionEvidenceStatus.SATISFIED,
                    observation = qualifyingAcknowledgement,
                    evaluation = latestEvaluation,
                    detail = "postconditions satisfied by stable local samples and Core ACK",
                )
            }

            val remainingMillis = remainingMillis(deadlineNanos)
            if (remainingMillis <= 0) {
                break
            }
            synchronized(monitor) {
                monitor.wait(minOf(remainingMillis, pollIntervalMillis))
            }
        }

        if (cancelled()) {
            return PostActionEvidenceResult(
                status = PostActionEvidenceStatus.CANCELLED,
                evaluation = latestEvaluation,
                detail = "action was cancelled while waiting for post-action evidence",
            )
        }
        if (closed || !AccessibilityObservationBus.current().serviceConnected) {
            return PostActionEvidenceResult(
                status = PostActionEvidenceStatus.OBSERVER_UNAVAILABLE,
                evaluation = latestEvaluation,
                detail = "Accessibility observer is unavailable",
            )
        }
        if (!observedPostLaunchSnapshot) {
            return PostActionEvidenceResult(
                status = PostActionEvidenceStatus.OBSERVATION_TIMEOUT,
                detail = "no post-launch Accessibility snapshot was observed",
            )
        }
        return when (latestEvaluation?.outcome) {
            PredicateOutcome.INDETERMINATE -> PostActionEvidenceResult(
                status = PostActionEvidenceStatus.INDETERMINATE,
                evaluation = latestEvaluation,
                detail = "postcondition resolution remained indeterminate",
            )

            PredicateOutcome.UNSATISFIED,
            PredicateOutcome.SATISFIED,
            null,
            -> PostActionEvidenceResult(
                status = PostActionEvidenceStatus.UNSATISFIED,
                evaluation = latestEvaluation,
                detail = if (latestEvaluation?.outcome == PredicateOutcome.SATISFIED) {
                    "local postconditions were satisfied but matching Core ACK did not arrive"
                } else {
                    "postconditions were not satisfied before timeout"
                },
            )
        }
    }

    override fun close() {
        if (closed) {
            return
        }
        closed = true
        localSubscription.close()
        acknowledgementSubscription.close()
        synchronized(monitor) {
            monitor.notifyAll()
        }
    }

    private fun deadlineAfter(timeoutMillis: Long): Long {
        val timeoutNanos = TimeUnit.MILLISECONDS.toNanos(timeoutMillis)
        val now = monotonicNanos()
        return if (Long.MAX_VALUE - now < timeoutNanos) Long.MAX_VALUE else now + timeoutNanos
    }

    private fun remainingMillis(deadlineNanos: Long): Long {
        val remaining = deadlineNanos - monotonicNanos()
        if (remaining <= 0) {
            return 0
        }
        return TimeUnit.NANOSECONDS.toMillis(remaining).coerceAtLeast(1)
    }

    private companion object {
        const val DEFAULT_POLL_INTERVAL_MILLIS = 200L
    }
}
