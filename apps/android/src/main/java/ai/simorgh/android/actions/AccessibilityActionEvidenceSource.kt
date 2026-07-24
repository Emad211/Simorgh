package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilityAcknowledgementBus
import ai.simorgh.android.accessibility.AccessibilityCaptureController
import ai.simorgh.android.accessibility.AccessibilityObservationBus
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.accessibility.AcknowledgedAccessibilityObservation
import java.io.Closeable
import java.util.ArrayDeque
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
    private val localHistory = ArrayDeque<AccessibilitySnapshot>()
    private val acknowledgementHistory = ArrayDeque<AcknowledgedAccessibilityObservation>()

    @Volatile
    private var closed = false

    private val localSubscription: Closeable
    private val acknowledgementSubscription: Closeable

    init {
        require(pollIntervalMillis in 25..1_000) {
            "poll interval must be in 25..1000 milliseconds"
        }
        AccessibilityObservationBus.current().latestSnapshot?.let { snapshot ->
            appendLocalLocked(snapshot)
        }
        AccessibilityAcknowledgementBus.latest()?.let { observation ->
            appendAcknowledgedLocked(observation)
        }
        localSubscription = AccessibilityObservationBus.subscribe { state ->
            val snapshot = state.latestSnapshot ?: return@subscribe
            synchronized(monitor) {
                appendLocalLocked(snapshot)
                monitor.notifyAll()
            }
        }
        acknowledgementSubscription = AccessibilityAcknowledgementBus.subscribe { value ->
            synchronized(monitor) {
                appendAcknowledgedLocked(value)
                monitor.notifyAll()
            }
        }
    }

    override fun latestAcknowledged(): AcknowledgedAccessibilityObservation? =
        synchronized(monitor) { acknowledgementHistory.peekLast() }

    override fun requestFreshLocalSnapshot(
        timeoutMillis: Long,
        cancelled: () -> Boolean,
    ): AccessibilitySnapshot? {
        require(timeoutMillis > 0)
        val baselineId = synchronized(monitor) { localHistory.peekLast()?.snapshotId }
        val requestedAtMs = wallClockMillis()
        if (!captureRequester()) {
            return null
        }
        val deadlineNanos = deadlineAfter(timeoutMillis)

        while (!closed && !cancelled()) {
            synchronized(monitor) {
                val candidate = localHistory.lastOrNull { snapshot ->
                    snapshot.snapshotId != baselineId &&
                        snapshot.capturedAtMs >= requestedAtMs
                }
                if (candidate != null) {
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
        val processedSnapshotIds = HashSet<String>()
        var lastCaptureRequestAtNanos = Long.MIN_VALUE
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

            val localSnapshots: List<AccessibilitySnapshot>
            val acknowledgements: List<AcknowledgedAccessibilityObservation>
            synchronized(monitor) {
                localSnapshots = localHistory.toList()
                acknowledgements = acknowledgementHistory.toList()
            }

            localSnapshots.forEach { local ->
                if (
                    !processedSnapshotIds.add(local.snapshotId) ||
                    local.snapshotId == before.snapshot.snapshotId ||
                    local.capturedAtMs < launchedAtMs
                ) {
                    return@forEach
                }
                observedPostLaunchSnapshot = true
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

            val qualifyingAcknowledgement = acknowledgements.lastOrNull { evidence ->
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

    private fun appendLocalLocked(snapshot: AccessibilitySnapshot) {
        if (localHistory.peekLast()?.snapshotId == snapshot.snapshotId) {
            return
        }
        localHistory.addLast(snapshot)
        while (localHistory.size > MAX_HISTORY_ENTRIES) {
            localHistory.removeFirst()
        }
    }

    private fun appendAcknowledgedLocked(observation: AcknowledgedAccessibilityObservation) {
        val previous = acknowledgementHistory.peekLast()
        if (
            previous?.streamId == observation.streamId &&
            previous.sequence == observation.sequence &&
            previous.snapshot.snapshotId == observation.snapshot.snapshotId
        ) {
            return
        }
        acknowledgementHistory.addLast(observation)
        while (acknowledgementHistory.size > MAX_HISTORY_ENTRIES) {
            acknowledgementHistory.removeFirst()
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
        const val MAX_HISTORY_ENTRIES = 64
    }
}
