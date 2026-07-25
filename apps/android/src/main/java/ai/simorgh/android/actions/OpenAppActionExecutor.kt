package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilitySnapshotFingerprint
import ai.simorgh.android.accessibility.AcknowledgedAccessibilityObservation
import ai.simorgh.android.time.CoreClock
import ai.simorgh.android.time.CoreClockBus
import ai.simorgh.android.time.CoreExecutionBudget
import ai.simorgh.android.time.CoreExecutionClockFailureKind
import ai.simorgh.android.time.CoreExecutionLease
import ai.simorgh.android.time.CoreExecutionLeaseStart
import ai.simorgh.android.time.LegacyWallClockCoreClock
import ai.simorgh.android.time.beginExecutionLease
import java.io.Closeable
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

class OpenAppActionExecutor(
    private val launcher: OpenAppLauncher,
    private val evidenceSource: OpenAppEvidenceSource,
    private val coreClock: CoreClock = CoreClockBus,
    private val executor: ExecutorService = Executors.newSingleThreadExecutor(),
) : AndroidActionHandler, Closeable {
    /** Compatibility constructor for deterministic fixtures that supply one synthetic epoch. */
    constructor(
        launcher: OpenAppLauncher,
        evidenceSource: OpenAppEvidenceSource,
        wallClockMillis: () -> Long,
        executor: ExecutorService = Executors.newSingleThreadExecutor(),
    ) : this(
        launcher = launcher,
        evidenceSource = evidenceSource,
        coreClock = LegacyWallClockCoreClock(wallClockMillis),
        executor = executor,
    )

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
            val fallback = safeCoreTime(command)
            val started = execution.startedAtCoreTimeMs.get()
                .takeIf { value -> value >= 0 }
                ?: fallback
            val finished = execution.lease.get()
                ?.coreTimeNowMs()
                ?.coerceAtLeast(started)
                ?: fallback.coerceAtLeast(started)
            result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.INTERNAL_ERROR,
                startedAtMs = started,
                finishedAtMs = finished,
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
        if (execution.cancelled.get()) {
            val now = safeCoreTime(command)
            return cancelledResult(
                command = command,
                startedAtMs = now,
                finishedAtMs = now,
                attempts = 0,
            )
        }

        val lease = when (
            val start = coreClock.beginExecutionLease(
                issuedAtCoreTimeMs = command.issuedAtMs,
                deadlineAtCoreTimeMs = command.deadlineAtMs,
            )
        ) {
            is CoreExecutionLeaseStart.Available -> start.lease
            is CoreExecutionLeaseStart.Unavailable -> {
                val timestamp = start.fallbackCoreTimeMs
                    .coerceAtLeast(command.issuedAtMs)
                    .coerceAtLeast(0)
                return result(
                    command = command,
                    outcome = ActionOutcome.BLOCKED,
                    failureCode = if (start.kind == CoreExecutionClockFailureKind.EXPIRED) {
                        ActionFailureCode.EXPIRED
                    } else {
                        ActionFailureCode.PRECONDITION_FAILED
                    },
                    startedAtMs = timestamp,
                    finishedAtMs = timestamp,
                    attempts = 0,
                    detail = (
                        "Core clock could not authorize open_app execution: ${start.detail}"
                        ).take(MAX_DETAIL_LENGTH),
                )
            }
        }
        execution.lease.set(lease)
        val startedAtMs = lease.startedAtCoreTimeMs
            .coerceAtLeast(command.issuedAtMs)
            .coerceAtLeast(0)
        execution.startedAtCoreTimeMs.set(startedAtMs)

        if (execution.cancelled.get()) {
            return cancelledResult(
                command = command,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAt(lease, startedAtMs),
                attempts = 0,
            )
        }

        val initiallyAcknowledged = evidenceSource.latestAcknowledged()
            ?: return result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.PRECONDITION_FAILED,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAt(lease, startedAtMs),
                attempts = 0,
                detail = "no Accessibility observation acknowledged by Core is available",
            )
        val initialPreconditionFailure = validatePrecondition(
            command = command,
            observation = initiallyAcknowledged,
            nowElapsedRealtimeMs = coreClock.elapsedRealtimeMs(),
        )
        if (initialPreconditionFailure != null) {
            return result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.PRECONDITION_FAILED,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAt(lease, startedAtMs),
                attempts = 0,
                before = initiallyAcknowledged.toReference(),
                detail = initialPreconditionFailure,
            )
        }

        val captureBudget = when (
            val budget = lease.remainingBudget(PRE_LAUNCH_CAPTURE_TIMEOUT_MILLIS)
        ) {
            is CoreExecutionBudget.Available -> budget.milliseconds
            is CoreExecutionBudget.Unavailable -> return executionBoundaryFailure(
                command = command,
                lease = lease,
                startedAtMs = startedAtMs,
                attempts = 0,
                before = initiallyAcknowledged.toReference(),
                budget = budget,
                boundary = "fresh pre-launch observation",
                launchAccepted = false,
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
                finishedAtMs = finishedAt(lease, startedAtMs),
                attempts = 0,
                before = initiallyAcknowledged.toReference(),
            )
        }
        if (freshBefore == null) {
            return result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.OBSERVATION_TIMEOUT,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAt(lease, startedAtMs),
                attempts = 0,
                before = initiallyAcknowledged.toReference(),
                detail = "fresh pre-launch Accessibility snapshot was unavailable",
            )
        }
        val freshFingerprint = AccessibilitySnapshotFingerprint.calculate(freshBefore)
        if (freshFingerprint != initiallyAcknowledged.stateFingerprint) {
            return result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.PRECONDITION_FAILED,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAt(lease, startedAtMs),
                attempts = 0,
                before = initiallyAcknowledged.toReference(),
                detail = "UI changed after the last Core-acknowledged observation",
            )
        }

        val currentlyAcknowledged = evidenceSource.latestAcknowledged()
            ?: return result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.PRECONDITION_FAILED,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAt(lease, startedAtMs),
                attempts = 0,
                before = initiallyAcknowledged.toReference(),
                detail = "Core acknowledgement was invalidated before the launch boundary",
            )
        val currentPreconditionFailure = validatePrecondition(
            command = command,
            observation = currentlyAcknowledged,
            nowElapsedRealtimeMs = coreClock.elapsedRealtimeMs(),
        )
        if (currentPreconditionFailure != null) {
            return result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.PRECONDITION_FAILED,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAt(lease, startedAtMs),
                attempts = 0,
                before = currentlyAcknowledged.toReference(),
                detail = "pre-launch evidence revalidation failed: $currentPreconditionFailure",
            )
        }
        if (currentlyAcknowledged.stateFingerprint != freshFingerprint) {
            return result(
                command = command,
                outcome = ActionOutcome.BLOCKED,
                failureCode = ActionFailureCode.PRECONDITION_FAILED,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAt(lease, startedAtMs),
                attempts = 0,
                before = currentlyAcknowledged.toReference(),
                detail = "current Core acknowledgement no longer matches the fresh local state",
            )
        }
        if (execution.cancelled.get()) {
            return cancelledResult(
                command = command,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAt(lease, startedAtMs),
                attempts = 0,
                before = currentlyAcknowledged.toReference(),
            )
        }

        val launchBoundary = lease.remainingBudget(MINIMUM_LAUNCH_BOUNDARY_BUDGET_MILLIS)
        if (launchBoundary is CoreExecutionBudget.Unavailable) {
            return executionBoundaryFailure(
                command = command,
                lease = lease,
                startedAtMs = startedAtMs,
                attempts = 0,
                before = currentlyAcknowledged.toReference(),
                budget = launchBoundary,
                boundary = "launch boundary",
                launchAccepted = false,
            )
        }

        val operation = command.operation as OpenAppOperation
        val existingState = UiPostconditionEvaluator.evaluate(
            snapshot = freshBefore,
            policy = command.verification,
        )
        if (operation.uri == null && existingState.outcome == PredicateOutcome.SATISFIED) {
            return result(
                command = command,
                outcome = ActionOutcome.SUCCEEDED,
                failureCode = ActionFailureCode.NONE,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAt(lease, startedAtMs),
                attempts = 0,
                before = currentlyAcknowledged.toReference(),
                after = currentlyAcknowledged.toReference(),
                predicates = existingState.evidence,
                detail = (
                    "declared postconditions already held in a fresh state matching the " +
                        "current Core-acknowledged fingerprint; launch was skipped"
                    ).take(MAX_DETAIL_LENGTH),
            )
        }

        val secondLaunchBoundary = lease.remainingBudget(MINIMUM_LAUNCH_BOUNDARY_BUDGET_MILLIS)
        if (secondLaunchBoundary is CoreExecutionBudget.Unavailable) {
            return executionBoundaryFailure(
                command = command,
                lease = lease,
                startedAtMs = startedAtMs,
                attempts = 0,
                before = currentlyAcknowledged.toReference(),
                budget = secondLaunchBoundary,
                boundary = "immediate pre-launch boundary",
                launchAccepted = false,
            )
        }
        val launchedAtElapsedRealtimeMs = coreClock.elapsedRealtimeMs()
        val launch = launcher.launch(operation)
        if (!launch.accepted) {
            return launchFailureResult(
                command = command,
                launch = launch,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAt(lease, startedAtMs),
                before = currentlyAcknowledged.toReference(),
            )
        }
        markLaunchAccepted()

        if (execution.cancelled.get()) {
            return cancelledResult(
                command = command,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAt(lease, startedAtMs),
                attempts = 1,
                before = currentlyAcknowledged.toReference(),
                detail = "cancellation arrived after Android accepted the launch request",
            )
        }

        val verificationBudget = when (
            val budget = lease.remainingBudget(command.verification.timeoutMs)
        ) {
            is CoreExecutionBudget.Available -> budget.milliseconds
            is CoreExecutionBudget.Unavailable -> return executionBoundaryFailure(
                command = command,
                lease = lease,
                startedAtMs = startedAtMs,
                attempts = 1,
                before = currentlyAcknowledged.toReference(),
                budget = budget,
                boundary = "post-launch verification",
                launchAccepted = true,
            )
        }

        val evidence = evidenceSource.awaitVerifiedObservation(
            currentlyAcknowledged,
            launchedAtElapsedRealtimeMs,
            command.verification,
            verificationBudget,
            execution.cancelled::get,
        )
        val finishedAtMs = finishedAt(lease, startedAtMs)
        val detail = (
            "${launch.adapter}: ${launch.detail}; ${evidence.detail}"
            ).take(MAX_DETAIL_LENGTH)
        return when (evidence.status) {
            PostActionEvidenceStatus.SATISFIED -> result(
                command = command,
                outcome = ActionOutcome.SUCCEEDED,
                failureCode = ActionFailureCode.NONE,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAtMs,
                attempts = 1,
                before = currentlyAcknowledged.toReference(),
                after = evidence.observation?.toReference(),
                predicates = evidence.evaluation?.evidence.orEmpty(),
                detail = detail,
            )

            PostActionEvidenceStatus.CANCELLED -> cancelledResult(
                command = command,
                startedAtMs = startedAtMs,
                finishedAtMs = finishedAtMs,
                attempts = 1,
                before = currentlyAcknowledged.toReference(),
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
                before = currentlyAcknowledged.toReference(),
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
                before = currentlyAcknowledged.toReference(),
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
                before = currentlyAcknowledged.toReference(),
                after = evidence.observation?.toReference(),
                predicates = evidence.evaluation?.evidence.orEmpty(),
                detail = detail,
            )
        }
    }

    private fun validatePrecondition(
        command: AndroidActionCommand,
        observation: AcknowledgedAccessibilityObservation,
        nowElapsedRealtimeMs: Long,
    ): String? {
        val precondition = command.precondition
        if (nowElapsedRealtimeMs < observation.capturedAtElapsedRealtimeMs) {
            return "acknowledged observation monotonic timestamp is in the future"
        }
        val age = nowElapsedRealtimeMs - observation.capturedAtElapsedRealtimeMs
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
            precondition.expectedActivePackage != observation.activePackage
        ) {
            return "active package does not match command precondition"
        }
        return null
    }

    private fun executionBoundaryFailure(
        command: AndroidActionCommand,
        lease: CoreExecutionLease,
        startedAtMs: Long,
        attempts: Int,
        before: ObservationReference?,
        budget: CoreExecutionBudget.Unavailable,
        boundary: String,
        launchAccepted: Boolean,
    ): AndroidActionResult {
        val expired = budget.kind == CoreExecutionClockFailureKind.EXPIRED
        return result(
            command = command,
            outcome = when {
                launchAccepted && expired -> ActionOutcome.TIMED_OUT
                else -> ActionOutcome.BLOCKED
            },
            failureCode = when {
                launchAccepted && expired -> ActionFailureCode.OBSERVATION_TIMEOUT
                launchAccepted -> ActionFailureCode.INTERNAL_ERROR
                expired -> ActionFailureCode.EXPIRED
                else -> ActionFailureCode.PRECONDITION_FAILED
            },
            startedAtMs = startedAtMs,
            finishedAtMs = finishedAt(lease, startedAtMs),
            attempts = attempts,
            before = before,
            detail = (
                "$boundary could not proceed under the bounded Core clock: ${budget.detail}"
                ).take(MAX_DETAIL_LENGTH),
        )
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
        finishedAtMs: Long,
        attempts: Int,
        before: ObservationReference? = null,
        after: ObservationReference? = null,
        detail: String = "open_app action was cancelled",
    ): AndroidActionResult = result(
        command = command,
        outcome = ActionOutcome.CANCELLED,
        failureCode = ActionFailureCode.CANCELLED,
        startedAtMs = startedAtMs,
        finishedAtMs = finishedAtMs,
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
            snapshotId = snapshotId,
            stateFingerprint = stateFingerprint,
            capturedAtMs = capturedAtMs,
            activePackage = activePackage,
        )

    private fun safeCoreTime(command: AndroidActionCommand): Long =
        coreClock.estimatedCoreTimeMs()
            ?.coerceAtLeast(command.issuedAtMs)
            ?.coerceAtLeast(0)
            ?: command.issuedAtMs.coerceAtLeast(0)

    private fun finishedAt(lease: CoreExecutionLease, startedAtMs: Long): Long =
        lease.coreTimeNowMs().coerceAtLeast(startedAtMs)

    private data class ActiveExecution(
        val commandId: String,
        val actionId: String,
        val cancelled: AtomicBoolean = AtomicBoolean(false),
        val startedAtCoreTimeMs: AtomicLong = AtomicLong(UNSET_CORE_TIME),
        val lease: AtomicReference<CoreExecutionLease?> = AtomicReference(null),
    )

    private companion object {
        const val PRE_LAUNCH_CAPTURE_TIMEOUT_MILLIS = 2_000L
        const val MINIMUM_LAUNCH_BOUNDARY_BUDGET_MILLIS = 1L
        const val MAX_DETAIL_LENGTH = 2_000
        const val UNSET_CORE_TIME = -1L
    }
}
