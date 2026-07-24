package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.accessibility.AcknowledgedAccessibilityObservation
import java.io.Closeable
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

class OpenAppActionExecutor(
    private val launcher: OpenAppLauncher,
    private val evidenceSource: OpenAppEvidenceSource,
    private val wallClockMillis: () -> Long = System::currentTimeMillis,
    private val executor: ExecutorService = Executors.newSingleThreadExecutor(),
) : AndroidActionHandler, Closeable {
    private val active = AtomicReference<ActiveExecution?>(null)

    override fun submit(
        request: ReceivedAndroidAction,
        completion: AndroidActionCompletion,
    ): Boolean {
        if (request.command.operation !is OpenAppOperation) {
            return false
        }
        val execution = ActiveExecution(
            commandId = request.command.commandId,
            actionId = request.command.actionId,
        )
        if (!active.compareAndSet(null, execution)) {
            return false
        }

        return try {
            executor.execute {
                val result = executeSafely(request.command, execution)
                try {
                    completion.complete(result)
                } finally {
                    active.compareAndSet(execution, null)
                }
            }
            true
        } catch (error: RejectedExecutionException) {
            active.compareAndSet(execution, null)
            false
        }
    }

    override fun cancel(commandId: String, actionId: String, reason: String): Boolean {
        val execution = active.get() ?: return false
        if (execution.commandId != commandId || execution.actionId != actionId) {
            return false
        }
        execution.cancelled.set(true)
        return true
    }

    override fun close() {
        active.get()?.cancelled?.set(true)
        executor.shutdownNow()
        evidenceSource.close()
    }

    private fun executeSafely(
        command: AndroidActionCommand,
        execution: ActiveExecution,
    ): AndroidActionResult {
        var launchAccepted = false
        return try {
            execute(command, execution) { launchAccepted = true }
        } catch (error: Exception) {
            val now = wallClockMillis().coerceAtLeast(0)
            result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.INTERNAL_ERROR,
                startedAtMs = now,
                finishedAtMs = now,
                attempts = if (launchAccepted) 1 else 0,
                detail = (
                    "open_app executor failed with ${error.javaClass.simpleName}; " +
                        "visible outcome is uncertain and the command will not be replayed"
                    ).take(MAX_DETAIL_LENGTH),
            )
        }
    }

    private fun execute(
        command: AndroidActionCommand,
        execution: ActiveExecution,
        markLaunchAccepted: () -> Unit,
    ): AndroidActionResult {
        val startedAtMs = wallClockMillis().coerceAtLeast(0)
        if (execution.cancelled.get()) {
            return cancelledResult(command, startedAtMs, attempts = 0)
        }
        if (startedAtMs >= command.deadlineAtMs) {
            return result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.EXPIRED,
                startedAtMs = startedAtMs,
                finishedAtMs = startedAtMs,
                attempts = 0,
                detail = "open_app command deadline elapsed before execution",
            )
        }

        val acknowledgedBefore = evidenceSource.latestAcknowledged()
            ?: return result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.PRECONDITION_FAILED,
                startedAtMs = startedAtMs,
                finishedAtMs = wallClockMillis().coerceAtLeast(startedAtMs),
                attempts = 0,
                detail = "no Accessibility observation acknowledged by Core is available",
            )
        val preconditionFailure = validatePrecondition(
            command = command,
            observation = acknowledgedBefore,
            nowMs = startedAtMs,
        )
        if (preconditionFailure != null) {
            return result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.PRECONDITION_FAILED,
                startedAtMs = startedAtMs,
                finishedAtMs = wallClockMillis().coerceAtLeast(startedAtMs),
                attempts = 0,
                before = acknowledgedBefore.toReference(),
                detail = preconditionFailure,
            )
        }

        val captureBudget = remainingBudget(
            command = command,
            requestedMillis = PRE_LAUNCH_CAPTURE_TIMEOUT_MILLIS,
        )
        if (captureBudget <= 0) {
            return result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.EXPIRED,
                startedAtMs = startedAtMs,
                finishedAtMs = wallClockMillis().coerceAtLeast(startedAtMs),
                attempts = 0,
                before = acknowledgedBefore.toReference(),
                detail = "no deadline budget remained for a fresh pre-launch observation",
            )
        }
        val freshBefore = evidenceSource.requestFreshLocalSnapshot(
            timeoutMillis = captureBudget,
            cancelled = execution.cancelled::get,
        )
        if (execution.cancelled.get()) {
            return cancelledResult(
                command = command,
                startedAtMs = startedAtMs,
                attempts = 0,
                before = acknowledgedBefore.toReference(),
            )
        }
        if (freshBefore == null) {
            return result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.OBSERVATION_TIMEOUT,
                startedAtMs = startedAtMs,
                finishedAtMs = wallClockMillis().coerceAtLeast(startedAtMs),
                attempts = 0,
                before = acknowledgedBefore.toReference(),
                detail = "fresh pre-launch Accessibility snapshot was unavailable",
            )
        }
        val freshFingerprint = AccessibilitySnapshotFingerprint.calculate(freshBefore)
        if (freshFingerprint != acknowledgedBefore.stateFingerprint) {
            return result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.PRECONDITION_FAILED,
                startedAtMs = startedAtMs,
                finishedAtMs = wallClockMillis().coerceAtLeast(startedAtMs),
                attempts = 0,
                before = acknowledgedBefore.toReference(),
                detail = "UI changed after the last Core-acknowledged observation",
            )
        }

        val operation = command.operation as OpenAppOperation
        val launchedAtMs = wallClockMillis().coerceAtLeast(startedAtMs)
        val launch = launcher.launch(operation)
        if (!launch.accepted) {
            return launchFailureResult(
                command = command,
                launch = launch,
                startedAtMs = startedAtMs,
                finishedAtMs = wallClockMillis().coerceAtLeast(launchedAtMs),
                before = acknowledgedBefore.toReference(),
            )
        }
        markLaunchAccepted()

        if (execution.cancelled.get()) {
            return cancelledResult(
                command = command,
                startedAtMs = startedAtMs,
                attempts = 1,
                before = acknowledgedBefore.toReference(),
                detail = "cancellation arrived after Android accepted the launch request",
            )
        }

        val verificationBudget = remainingBudget(
            command = command,
            requestedMillis = command.verification.timeoutMs,
        )
        if (verificationBudget <= 0) {
            return result(
                command = command,
                outcome = ActionOutcome.TIMED_OUT,
                failureCode = ActionFailureCode.OBSERVATION_TIMEOUT,
                startedAtMs = startedAtMs,
                finishedAtMs = wallClockMillis().coerceAtLeast(launchedAtMs),
                attempts = 1,
                before = acknowledgedBefore.toReference(),
                detail = "command deadline elapsed before post-launch verification",
            )
        }

        val evidence = evidenceSource.awaitVerifiedObservation(
            before = acknowledgedBefore,
            launchedAtMs = launchedAtMs,
            policy = command.verification,
            timeoutMillis = verificationBudget,
            cancelled = execution.cancelled::get,
        )
        val finishedAtMs = wallClockMillis().coerceAtLeast(launchedAtMs)
        val detail = "${launch.adapter}: ${launch.detail}; ${evidence.detail}".take(MAX_DETAIL_LENGTH)
        return when (evidence.status) {
            PostActionEvidenceStatus.SATISFIED -> result(
                command = command,
                outcome = ActionOutcome.SUCCEEDED,
                failureCode = ActionFailureCode.NONE,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAtMs,
                attempts = 1,
                before = acknowledgedBefore.toReference(),
                after = evidence.observation?.toReference(),
                predicates = evidence.evaluation?.evidence.orEmpty(),
                detail = detail,
            )

            PostActionEvidenceStatus.CANCELLED -> cancelledResult(
                command = command,
                startedAtMs = startedAtMs,
                attempts = 1,
                before = acknowledgedBefore.toReference(),
                after = evidence.observation?.toReference(),
                detail = detail,
            )

            PostActionEvidenceStatus.INDETERMINATE -> result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.POSTCONDITION_FAILED,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAtMs,
                attempts = 1,
                before = acknowledgedBefore.toReference(),
                after = evidence.observation?.toReference(),
                predicates = evidence.evaluation?.evidence.orEmpty(),
                detail = detail,
            )

            PostActionEvidenceStatus.UNSATISFIED -> result(
                command = command,
                outcome = ActionOutcome.FAILED,
                failureCode = ActionFailureCode.POSTCONDITION_FAILED,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAtMs,
                attempts = 1,
                before = acknowledgedBefore.toReference(),
                after = evidence.observation?.toReference(),
                predicates = evidence.evaluation?.evidence.orEmpty(),
                detail = detail,
            )

            PostActionEvidenceStatus.OBSERVATION_TIMEOUT,
            PostActionEvidenceStatus.OBSERVER_UNAVAILABLE,
            -> result(
                command = command,
                outcome = ActionOutcome.TIMED_OUT,
                failureCode = ActionFailureCode.OBSERVATION_TIMEOUT,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAtMs,
                attempts = 1,
                before = acknowledgedBefore.toReference(),
                after = evidence.observation?.toReference(),
                predicates = evidence.evaluation?.evidence.orEmpty(),
                detail = detail,
            )
        }
    }

    private fun validatePrecondition(
        command: AndroidActionCommand,
        observation: AcknowledgedAccessibilityObservation,
        nowMs: Long,
    ): String? {
        val precondition = command.precondition
        val age = nowMs - observation.snapshot.capturedAtMs
        if (age < 0) {
            return "acknowledged observation timestamp is in the future"
        }
        if (age > precondition.maximumAgeMs) {
            return "acknowledged observation age ${age}ms exceeds ${precondition.maximumAgeMs}ms"
        }
        if (
            precondition.expectedStreamId != null &&
            precondition.expectedStreamId != observation.streamId
        ) {
            return "observation stream_id does not match command precondition"
        }
        if (
            precondition.minimumSequence != null &&
            observation.sequence < precondition.minimumSequence
        ) {
            return "observation sequence is below command minimum_sequence"
        }
        if (
            precondition.expectedStateFingerprint != null &&
            precondition.expectedStateFingerprint != observation.stateFingerprint
        ) {
            return "observation state fingerprint does not match command precondition"
        }
        if (
            precondition.expectedActivePackage != null &&
            precondition.expectedActivePackage != observation.snapshot.activePackage
        ) {
            return "active package does not match command precondition"
        }
        return null
    }

    private fun launchFailureResult(
        command: AndroidActionCommand,
        launch: OpenAppLaunchAttempt,
        startedAtMs: Long,
        finishedAtMs: Long,
        before: ObservationReference,
    ): AndroidActionResult {
        val (outcome, code) = when (launch.status) {
            OpenAppLaunchStatus.BACKGROUND_START_BLOCKED ->
                ActionOutcome.BLOCKED to ActionFailureCode.UNSUPPORTED_CAPABILITY
            OpenAppLaunchStatus.TARGET_NOT_FOUND ->
                ActionOutcome.FAILED to ActionFailureCode.TARGET_NOT_FOUND
            OpenAppLaunchStatus.INVALID_URI ->
                ActionOutcome.BLOCKED to ActionFailureCode.INVALID_COMMAND
            OpenAppLaunchStatus.REJECTED ->
                ActionOutcome.FAILED to ActionFailureCode.ACTION_REJECTED
            OpenAppLaunchStatus.ACCEPTED ->
                ActionOutcome.BLOCKED to ActionFailureCode.INTERNAL_ERROR
        }
        return result(
            command = command,
            outcome = outcome,
            failureCode = code,
            startedAtMs = startedAtMs,
            finishedAtMs = finishedAtMs,
            attempts = 0,
            before = before,
            detail = "${launch.adapter}: ${launch.detail}".take(MAX_DETAIL_LENGTH),
        )
    }

    private fun cancelledResult(
        command: AndroidActionCommand,
        startedAtMs: Long,
        attempts: Int,
        before: ObservationReference? = null,
        after: ObservationReference? = null,
        detail: String = "open_app action was cancelled",
    ): AndroidActionResult = result(
        command = command,
        outcome = ActionOutcome.CANCELLED,
        failureCode = ActionFailureCode.CANCELLED,
        startedAtMs = startedAtMs,
        finishedAtMs = wallClockMillis().coerceAtLeast(startedAtMs),
        attempts = attempts,
        before = before,
        after = after,
        detail = detail,
    )

    private fun result(
        command: AndroidActionCommand,
        outcome: ActionOutcome,
        failureCode: ActionFailureCode,
        startedAtMs: Long,
        finishedAtMs: Long,
        attempts: Int,
        before: ObservationReference? = null,
        after: ObservationReference? = null,
        predicates: List<PredicateEvidence> = emptyList(),
        detail: String,
    ): AndroidActionResult = AndroidActionContractValidator.validate(
        AndroidActionResult(
            commandId = command.commandId,
            actionId = command.actionId,
            outcome = outcome,
            failureCode = failureCode,
            startedAtMs = startedAtMs,
            finishedAtMs = finishedAtMs,
            attempts = attempts,
            beforeObservation = before,
            afterObservation = after,
            predicates = predicates,
            detail = detail.take(MAX_DETAIL_LENGTH),
        ),
    )

    private fun AcknowledgedAccessibilityObservation.toReference(): ObservationReference =
        ObservationReference(
            streamId = streamId,
            sequence = sequence,
            snapshotId = snapshot.snapshotId,
            stateFingerprint = stateFingerprint,
            capturedAtMs = snapshot.capturedAtMs,
            activePackage = snapshot.activePackage,
        )

    private fun remainingBudget(command: AndroidActionCommand, requestedMillis: Long): Long {
        val remaining = command.deadlineAtMs - wallClockMillis()
        return minOf(requestedMillis, remaining).coerceAtLeast(0)
    }

    private data class ActiveExecution(
        val commandId: String,
        val actionId: String,
        val cancelled: AtomicBoolean = AtomicBoolean(false),
    )

    private companion object {
        const val PRE_LAUNCH_CAPTURE_TIMEOUT_MILLIS = 2_000L
        const val MAX_DETAIL_LENGTH = 2_000
    }
}
