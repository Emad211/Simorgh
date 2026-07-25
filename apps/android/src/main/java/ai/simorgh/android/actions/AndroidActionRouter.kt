package ai.simorgh.android.actions

import ai.simorgh.android.protocol.ActionCancelAckStatus
import ai.simorgh.android.protocol.ActionCommandAckStatus
import ai.simorgh.android.protocol.ActionResultAckStatus
import ai.simorgh.android.protocol.DeviceActionCancelPayload
import ai.simorgh.android.protocol.DeviceActionResultAckPayload
import ai.simorgh.android.time.CoreClock
import ai.simorgh.android.time.CoreClockBus
import ai.simorgh.android.time.CoreExecutionClockFailureKind
import ai.simorgh.android.time.CoreExecutionLeaseStart
import ai.simorgh.android.time.LegacyWallClockCoreClock
import ai.simorgh.android.time.beginExecutionLease
import java.security.MessageDigest
import java.util.UUID

data class ActionCommandReceipt(
    val status: ActionCommandAckStatus,
    val detail: String = "",
)

data class PendingActionResultDelivery(
    val commandEnvelopeId: String,
    val resultMessageId: String,
    val result: AndroidActionResult,
)

class AndroidActionRouter(
    private val ledger: ActionLedger,
    private val handlerProvider: () -> AndroidActionHandler? = AndroidActionHandlerRegistry::current,
    private val resultEmitter: (PendingActionResultDelivery) -> Unit,
    private val eventListener: (String) -> Unit = {},
    private val coreClock: CoreClock = CoreClockBus,
) {
    /** Compatibility constructor for deterministic JVM fixtures using one synthetic time source. */
    constructor(
        ledger: ActionLedger,
        handlerProvider: () -> AndroidActionHandler? = AndroidActionHandlerRegistry::current,
        resultEmitter: (PendingActionResultDelivery) -> Unit,
        nowMillis: () -> Long,
        eventListener: (String) -> Unit = {},
    ) : this(
        ledger = ledger,
        handlerProvider = handlerProvider,
        resultEmitter = resultEmitter,
        eventListener = eventListener,
        coreClock = LegacyWallClockCoreClock(nowMillis),
    )

    private val lock = Any()
    private var activeInProcess: PersistedActionEntry? = null

    fun receiveCommand(
        commandEnvelopeId: String,
        rawCommand: AndroidActionCommand,
    ): ActionCommandReceipt {
        val command = runCatching {
            requireUuid(commandEnvelopeId, "command envelope message_id")
            AndroidActionContractValidator.validate(rawCommand)
        }.getOrElse { error ->
            return ActionCommandReceipt(
                status = ActionCommandAckStatus.REJECTED,
                detail = error.message.orEmpty().take(MAX_DETAIL_LENGTH),
            )
        }
        val commandHash = hashCommand(command)
        val plan = synchronized(lock) {
            planCommand(
                commandEnvelopeId = commandEnvelopeId,
                command = command,
                commandHash = commandHash,
            )
        }

        return when (plan) {
            is CommandPlan.Return -> {
                plan.delivery?.let(resultEmitter)
                plan.receipt
            }

            is CommandPlan.Submit -> submitOutsideLock(plan)
        }
    }

    fun receiveCancellation(
        cancellation: DeviceActionCancelPayload,
    ): ActionCancelAckStatus {
        val plan = synchronized(lock) { planCancellation(cancellation) }
        return when (plan) {
            is CancellationPlan.Return -> {
                plan.delivery?.let(resultEmitter)
                plan.status
            }

            is CancellationPlan.Invoke -> {
                val accepted = runCatching {
                    plan.handler.cancel(
                        cancellation.commandId,
                        cancellation.actionId,
                        cancellation.reason,
                    )
                }.getOrElse { error ->
                    eventListener("action cancellation failed: ${error.javaClass.simpleName}")
                    false
                }
                if (accepted) {
                    ActionCancelAckStatus.ACCEPTED
                } else {
                    ActionCancelAckStatus.NOT_FOUND
                }
            }
        }
    }

    fun acknowledgeResult(
        acknowledgement: DeviceActionResultAckPayload,
        correlationId: String?,
    ): Boolean {
        var rejectedStatus: ActionResultAckStatus? = null
        val accepted = synchronized(lock) {
            val entry = (ledger.load() as? ActionLedgerLoadResult.Loaded)?.entry
                ?: return@synchronized false
            if (entry.phase != ActionLedgerPhase.COMPLETED) {
                return@synchronized false
            }
            if (
                entry.command.commandId != acknowledgement.commandId ||
                entry.command.actionId != acknowledgement.actionId ||
                entry.resultMessageId != correlationId
            ) {
                return@synchronized false
            }

            when (acknowledgement.status) {
                ActionResultAckStatus.ACCEPTED,
                ActionResultAckStatus.DUPLICATE,
                -> {
                    ledger.save(entry.copy(resultAcknowledged = true).validated())
                    true
                }

                ActionResultAckStatus.UNKNOWN_ACTION,
                ActionResultAckStatus.REJECTED,
                -> {
                    rejectedStatus = acknowledgement.status
                    false
                }
            }
        }
        rejectedStatus?.let { status ->
            eventListener("Core did not accept action result: ${status.name.lowercase()}")
        }
        return accepted
    }

    fun recoverUnacknowledgedResult() {
        val delivery = synchronized(lock) {
            val entry = (ledger.load() as? ActionLedgerLoadResult.Loaded)?.entry
            entry?.pendingDelivery()
        }
        delivery?.let(resultEmitter)
    }

    private fun planCommand(
        commandEnvelopeId: String,
        command: AndroidActionCommand,
        commandHash: String,
    ): CommandPlan {
        when (val loaded = ledger.load()) {
            is ActionLedgerLoadResult.Corrupt -> return CommandPlan.Return(
                receipt = ActionCommandReceipt(
                    status = ActionCommandAckStatus.REJECTED,
                    detail = (
                        "encrypted action ledger is unreadable: ${loaded.detail}"
                        ).take(MAX_DETAIL_LENGTH),
                ),
            )

            is ActionLedgerLoadResult.Loaded -> {
                val entry = loaded.entry
                if (entry.matches(commandEnvelopeId, command, commandHash)) {
                    return planMatchingCommand(entry)
                }

                if (entry.phase == ActionLedgerPhase.ACTIVE) {
                    return CommandPlan.Return(
                        receipt = ActionCommandReceipt(
                            status = ActionCommandAckStatus.BUSY,
                            detail = "another action is active or awaiting recovery",
                        ),
                    )
                }
                if (!entry.resultAcknowledged) {
                    return CommandPlan.Return(
                        receipt = ActionCommandReceipt(
                            status = ActionCommandAckStatus.BUSY,
                            detail = "previous action result is awaiting Core acknowledgement",
                        ),
                        delivery = entry.pendingDelivery(),
                    )
                }
            }

            ActionLedgerLoadResult.Empty -> Unit
        }

        when (
            val clockAcceptance = coreClock.beginExecutionLease(
                issuedAtCoreTimeMs = command.issuedAtMs,
                deadlineAtCoreTimeMs = command.deadlineAtMs,
            )
        ) {
            is CoreExecutionLeaseStart.Available -> Unit
            is CoreExecutionLeaseStart.Unavailable -> {
                val expired = clockAcceptance.kind == CoreExecutionClockFailureKind.EXPIRED
                return CommandPlan.Return(
                    receipt = ActionCommandReceipt(
                        status = if (expired) {
                            ActionCommandAckStatus.EXPIRED
                        } else {
                            ActionCommandAckStatus.REJECTED
                        },
                        detail = (
                            "Core clock rejected Android command acceptance: " +
                                clockAcceptance.detail
                            ).take(MAX_DETAIL_LENGTH),
                    ),
                )
            }
        }

        val handler = handlerProvider()
            ?: return CommandPlan.Return(
                receipt = ActionCommandReceipt(
                    status = ActionCommandAckStatus.REJECTED,
                    detail = "Android action executor is not available",
                ),
            )

        val activeEntry = PersistedActionEntry(
            commandEnvelopeId = commandEnvelopeId,
            commandHash = commandHash,
            command = command,
            phase = ActionLedgerPhase.ACTIVE,
        ).validated()
        ledger.save(activeEntry)
        activeInProcess = activeEntry
        return CommandPlan.Submit(
            handler = handler,
            entry = activeEntry,
        )
    }

    private fun planMatchingCommand(
        entry: PersistedActionEntry,
    ): CommandPlan {
        if (entry.phase == ActionLedgerPhase.COMPLETED) {
            return CommandPlan.Return(
                receipt = ActionCommandReceipt(
                    status = ActionCommandAckStatus.DUPLICATE,
                    detail = "command was already completed",
                ),
                delivery = entry.pendingDelivery(),
            )
        }
        if (activeInProcess?.sameIdentity(entry) == true) {
            return CommandPlan.Return(
                receipt = ActionCommandReceipt(
                    status = ActionCommandAckStatus.DUPLICATE,
                    detail = "command is already active",
                ),
            )
        }

        val recovered = recoveryBlockedResult(entry)
        ledger.save(recovered)
        activeInProcess = null
        return CommandPlan.Return(
            receipt = ActionCommandReceipt(
                status = ActionCommandAckStatus.DUPLICATE,
                detail = "previous execution state was unknown after process restart",
            ),
            delivery = recovered.pendingDelivery(),
        )
    }

    private fun submitOutsideLock(plan: CommandPlan.Submit): ActionCommandReceipt {
        val entry = plan.entry
        val accepted = runCatching {
            plan.handler.submit(
                ReceivedAndroidAction(
                    commandEnvelopeId = entry.commandEnvelopeId,
                    command = entry.command,
                ),
                AndroidActionCompletion { result ->
                    complete(
                        commandEnvelopeId = entry.commandEnvelopeId,
                        commandHash = entry.commandHash,
                        command = entry.command,
                        result = result,
                    )
                },
            )
        }.getOrElse { error ->
            eventListener("action handler submit failed: ${error.javaClass.simpleName}")
            false
        }

        if (accepted) {
            return ActionCommandReceipt(status = ActionCommandAckStatus.ACCEPTED)
        }

        val rollback = synchronized(lock) { rollbackRejectedSubmit(entry) }
        rollback.delivery?.let(resultEmitter)
        return rollback.receipt
    }

    private fun rollbackRejectedSubmit(entry: PersistedActionEntry): CommandPlan.Return {
        val loaded = (ledger.load() as? ActionLedgerLoadResult.Loaded)?.entry
        if (loaded?.sameIdentity(entry) != true) {
            activeInProcess = null
            return CommandPlan.Return(
                receipt = ActionCommandReceipt(
                    status = ActionCommandAckStatus.REJECTED,
                    detail = "action ledger changed while executor rejected the command",
                ),
            )
        }
        if (loaded.phase == ActionLedgerPhase.COMPLETED) {
            activeInProcess = null
            eventListener(
                "action handler completed synchronously but returned rejected; preserving result",
            )
            return CommandPlan.Return(
                receipt = ActionCommandReceipt(
                    status = ActionCommandAckStatus.ACCEPTED,
                    detail = "executor completed synchronously",
                ),
                delivery = loaded.pendingDelivery(),
            )
        }

        activeInProcess = null
        ledger.clear()
        return CommandPlan.Return(
            receipt = ActionCommandReceipt(
                status = ActionCommandAckStatus.REJECTED,
                detail = "Android action executor rejected the command",
            ),
        )
    }

    private fun planCancellation(
        cancellation: DeviceActionCancelPayload,
    ): CancellationPlan {
        if (!isUuid(cancellation.commandId) || !isUuid(cancellation.actionId)) {
            return CancellationPlan.Return(ActionCancelAckStatus.NOT_FOUND)
        }

        val entry = (ledger.load() as? ActionLedgerLoadResult.Loaded)?.entry
            ?: return CancellationPlan.Return(ActionCancelAckStatus.NOT_FOUND)
        if (
            entry.command.commandId != cancellation.commandId ||
            entry.command.actionId != cancellation.actionId
        ) {
            return CancellationPlan.Return(ActionCancelAckStatus.NOT_FOUND)
        }
        if (entry.phase == ActionLedgerPhase.COMPLETED) {
            return CancellationPlan.Return(
                status = ActionCancelAckStatus.COMPLETED,
                delivery = entry.pendingDelivery(),
            )
        }

        val active = activeInProcess
        if (active == null || !active.sameIdentity(entry)) {
            val recovered = recoveryBlockedResult(entry)
            ledger.save(recovered)
            activeInProcess = null
            return CancellationPlan.Return(
                status = ActionCancelAckStatus.COMPLETED,
                delivery = recovered.pendingDelivery(),
            )
        }

        val handler = handlerProvider()
            ?: return CancellationPlan.Return(ActionCancelAckStatus.NOT_FOUND)
        return CancellationPlan.Invoke(handler)
    }

    private fun complete(
        commandEnvelopeId: String,
        commandHash: String,
        command: AndroidActionCommand,
        result: AndroidActionResult,
    ) {
        val validatedResult = runCatching {
            AndroidActionContractValidator.validate(result)
        }.getOrElse { error ->
            eventListener("action result validation failed: ${error.message.orEmpty()}")
            return
        }
        if (
            validatedResult.commandId != command.commandId ||
            validatedResult.actionId != command.actionId
        ) {
            eventListener("action result identifiers do not match active command")
            return
        }

        val plan = synchronized(lock) {
            planCompletion(
                commandEnvelopeId = commandEnvelopeId,
                commandHash = commandHash,
                command = command,
                result = validatedResult,
            )
        }
        plan.event?.let(eventListener)
        plan.delivery?.let(resultEmitter)
    }

    private fun planCompletion(
        commandEnvelopeId: String,
        commandHash: String,
        command: AndroidActionCommand,
        result: AndroidActionResult,
    ): CompletionPlan {
        val entry = (ledger.load() as? ActionLedgerLoadResult.Loaded)?.entry
            ?: return CompletionPlan(event = "action result arrived without a ledger entry")
        if (!entry.matches(commandEnvelopeId, command, commandHash)) {
            return CompletionPlan(event = "action result arrived for a replaced ledger entry")
        }
        if (entry.phase == ActionLedgerPhase.COMPLETED) {
            return if (entry.result != result) {
                CompletionPlan(
                    event = "action handler attempted to complete twice with different results",
                )
            } else {
                CompletionPlan(delivery = entry.pendingDelivery())
            }
        }

        val completed = entry.copy(
            phase = ActionLedgerPhase.COMPLETED,
            resultMessageId = UUID.randomUUID().toString(),
            result = result,
            resultAcknowledged = false,
        ).validated()
        ledger.save(completed)
        activeInProcess = null
        return CompletionPlan(delivery = completed.pendingDelivery())
    }

    private fun recoveryBlockedResult(
        entry: PersistedActionEntry,
    ): PersistedActionEntry {
        val now = coreClock.estimatedCoreTimeMs()
            ?.coerceAtLeast(entry.command.issuedAtMs)
            ?: entry.command.issuedAtMs.coerceAtLeast(0)
        val result = AndroidActionResult(
            commandId = entry.command.commandId,
            actionId = entry.command.actionId,
            outcome = ActionOutcome.BLOCKED,
            failureCode = ActionFailureCode.INTERNAL_ERROR,
            startedAtMs = now,
            finishedAtMs = now,
            attempts = 0,
            detail = (
                "execution state was unknown after Android process restart; " +
                    "command was not re-executed"
                ),
        )
        return entry.copy(
            phase = ActionLedgerPhase.COMPLETED,
            resultMessageId = UUID.randomUUID().toString(),
            result = result,
            resultAcknowledged = false,
        ).validated()
    }

    private fun hashCommand(command: AndroidActionCommand): String = MessageDigest
        .getInstance("SHA-256")
        .digest(AndroidActionJson.codec.encodeToString(AndroidActionCommand.serializer(), command))
        .joinToString(separator = "") { byte -> "%02x".format(byte.toInt() and 0xFF) }

    private fun PersistedActionEntry.matches(
        commandEnvelopeId: String,
        command: AndroidActionCommand,
        commandHash: String,
    ): Boolean =
        this.commandEnvelopeId == commandEnvelopeId &&
            this.command.commandId == command.commandId &&
            this.command.actionId == command.actionId &&
            this.commandHash == commandHash

    private fun PersistedActionEntry.sameIdentity(other: PersistedActionEntry): Boolean =
        commandEnvelopeId == other.commandEnvelopeId &&
            commandHash == other.commandHash &&
            command.commandId == other.command.commandId &&
            command.actionId == other.command.actionId

    private fun PersistedActionEntry.pendingDelivery(): PendingActionResultDelivery? {
        if (
            phase != ActionLedgerPhase.COMPLETED ||
            resultAcknowledged ||
            resultMessageId == null ||
            result == null
        ) {
            return null
        }
        return PendingActionResultDelivery(
            commandEnvelopeId = commandEnvelopeId,
            resultMessageId = resultMessageId,
            result = result,
        )
    }

    private fun requireUuid(value: String, field: String) {
        require(isUuid(value)) { "$field must be a UUID" }
    }

    private fun isUuid(value: String): Boolean =
        runCatching { UUID.fromString(value) }.isSuccess

    private sealed interface CommandPlan {
        data class Return(
            val receipt: ActionCommandReceipt,
            val delivery: PendingActionResultDelivery? = null,
        ) : CommandPlan

        data class Submit(
            val handler: AndroidActionHandler,
            val entry: PersistedActionEntry,
        ) : CommandPlan
    }

    private sealed interface CancellationPlan {
        data class Return(
            val status: ActionCancelAckStatus,
            val delivery: PendingActionResultDelivery? = null,
        ) : CancellationPlan

        data class Invoke(val handler: AndroidActionHandler) : CancellationPlan
    }

    private data class CompletionPlan(
        val delivery: PendingActionResultDelivery? = null,
        val event: String? = null,
    )

    private companion object {
        const val MAX_DETAIL_LENGTH = 1_000
    }
}
