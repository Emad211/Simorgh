package ai.simorgh.android.actions

import ai.simorgh.android.protocol.ActionCancelAckStatus
import ai.simorgh.android.protocol.ActionCommandAckStatus
import ai.simorgh.android.protocol.ActionResultAckStatus
import ai.simorgh.android.protocol.DeviceActionCancelPayload
import ai.simorgh.android.protocol.DeviceActionResultAckPayload
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
    private val nowMillis: () -> Long = System::currentTimeMillis,
    private val eventListener: (String) -> Unit = {},
) {
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
                detail = error.message.orEmpty().take(1_000),
            )
        }
        val commandHash = hashCommand(command)
        val now = nowMillis()

        val replayDelivery: PendingActionResultDelivery?
        synchronized(lock) {
            when (val loaded = ledger.load()) {
                is ActionLedgerLoadResult.Corrupt -> return ActionCommandReceipt(
                    status = ActionCommandAckStatus.REJECTED,
                    detail = "encrypted action ledger is unreadable: ${loaded.detail}".take(1_000),
                )

                is ActionLedgerLoadResult.Loaded -> {
                    val entry = loaded.entry
                    if (entry.matches(commandEnvelopeId, command, commandHash)) {
                        if (entry.phase == ActionLedgerPhase.COMPLETED) {
                            replayDelivery = entry.pendingDelivery()
                            replayDelivery?.let(resultEmitter)
                            return ActionCommandReceipt(
                                status = ActionCommandAckStatus.DUPLICATE,
                                detail = "command was already completed",
                            )
                        }
                        if (activeInProcess?.matches(commandEnvelopeId, command, commandHash) == true) {
                            return ActionCommandReceipt(
                                status = ActionCommandAckStatus.DUPLICATE,
                                detail = "command is already active",
                            )
                        }

                        val recovered = recoveryBlockedResult(entry, now)
                        ledger.save(recovered)
                        activeInProcess = null
                        recovered.pendingDelivery()?.let(resultEmitter)
                        return ActionCommandReceipt(
                            status = ActionCommandAckStatus.DUPLICATE,
                            detail = "previous execution state was unknown after process restart",
                        )
                    }

                    if (entry.phase == ActionLedgerPhase.ACTIVE) {
                        return ActionCommandReceipt(
                            status = ActionCommandAckStatus.BUSY,
                            detail = "another action is active or awaiting recovery",
                        )
                    }
                }

                ActionLedgerLoadResult.Empty -> Unit
            }

            if (command.deadlineAtMs <= now) {
                return ActionCommandReceipt(
                    status = ActionCommandAckStatus.EXPIRED,
                    detail = "command deadline elapsed before Android acceptance",
                )
            }

            val handler = handlerProvider()
                ?: return ActionCommandReceipt(
                    status = ActionCommandAckStatus.REJECTED,
                    detail = "Android action executor is not available",
                )

            val activeEntry = PersistedActionEntry(
                commandEnvelopeId = commandEnvelopeId,
                commandHash = commandHash,
                command = command,
                phase = ActionLedgerPhase.ACTIVE,
            ).validated()
            ledger.save(activeEntry)
            activeInProcess = activeEntry

            val accepted = runCatching {
                handler.submit(
                    ReceivedAndroidAction(
                        commandEnvelopeId = commandEnvelopeId,
                        command = command,
                    ),
                    AndroidActionCompletion { result ->
                        complete(
                            commandEnvelopeId = commandEnvelopeId,
                            commandHash = commandHash,
                            command = command,
                            result = result,
                        )
                    },
                )
            }.getOrElse { error ->
                eventListener("action handler submit failed: ${error.javaClass.simpleName}")
                false
            }

            if (!accepted) {
                activeInProcess = null
                ledger.clear()
                return ActionCommandReceipt(
                    status = ActionCommandAckStatus.REJECTED,
                    detail = "Android action executor rejected the command",
                )
            }
        }

        return ActionCommandReceipt(status = ActionCommandAckStatus.ACCEPTED)
    }

    fun receiveCancellation(
        cancellation: DeviceActionCancelPayload,
    ): ActionCancelAckStatus = synchronized(lock) {
        if (
            !isUuid(cancellation.commandId) ||
            !isUuid(cancellation.actionId)
        ) {
            return@synchronized ActionCancelAckStatus.NOT_FOUND
        }

        val loaded = ledger.load()
        val entry = (loaded as? ActionLedgerLoadResult.Loaded)?.entry
            ?: return@synchronized ActionCancelAckStatus.NOT_FOUND
        if (
            entry.command.commandId != cancellation.commandId ||
            entry.command.actionId != cancellation.actionId
        ) {
            return@synchronized ActionCancelAckStatus.NOT_FOUND
        }
        if (entry.phase == ActionLedgerPhase.COMPLETED) {
            return@synchronized ActionCancelAckStatus.COMPLETED
        }

        val active = activeInProcess
        if (active == null || active.command.actionId != cancellation.actionId) {
            return@synchronized ActionCancelAckStatus.NOT_FOUND
        }
        val accepted = handlerProvider()?.cancel(
            cancellation.commandId,
            cancellation.actionId,
            cancellation.reason,
        ) == true
        if (accepted) ActionCancelAckStatus.ACCEPTED else ActionCancelAckStatus.NOT_FOUND
    }

    fun acknowledgeResult(
        acknowledgement: DeviceActionResultAckPayload,
        correlationId: String?,
    ): Boolean = synchronized(lock) {
        val loaded = ledger.load()
        val entry = (loaded as? ActionLedgerLoadResult.Loaded)?.entry ?: return@synchronized false
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
                eventListener(
                    "Core did not accept action result: ${acknowledgement.status.name.lowercase()}",
                )
                false
            }
        }
    }

    fun recoverUnacknowledgedResult() {
        synchronized(lock) {
            val entry = (ledger.load() as? ActionLedgerLoadResult.Loaded)?.entry ?: return
            entry.pendingDelivery()?.let(resultEmitter)
        }
    }

    private fun complete(
        *,
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

        val delivery: PendingActionResultDelivery
        synchronized(lock) {
            val loaded = ledger.load()
            val entry = (loaded as? ActionLedgerLoadResult.Loaded)?.entry ?: return
            if (!entry.matches(commandEnvelopeId, command, commandHash)) {
                eventListener("action result arrived for a replaced ledger entry")
                return
            }
            if (entry.phase == ActionLedgerPhase.COMPLETED) {
                if (entry.result != validatedResult) {
                    eventListener("action handler attempted to complete twice with different results")
                }
                entry.pendingDelivery()?.let(resultEmitter)
                return
            }

            val completed = entry.copy(
                phase = ActionLedgerPhase.COMPLETED,
                resultMessageId = UUID.randomUUID().toString(),
                result = validatedResult,
                resultAcknowledged = false,
            ).validated()
            ledger.save(completed)
            activeInProcess = null
            delivery = requireNotNull(completed.pendingDelivery())
        }
        resultEmitter(delivery)
    }

    private fun recoveryBlockedResult(
        entry: PersistedActionEntry,
        now: Long,
    ): PersistedActionEntry {
        val result = AndroidActionResult(
            commandId = entry.command.commandId,
            actionId = entry.command.actionId,
            outcome = ActionOutcome.BLOCKED,
            failureCode = ActionFailureCode.INTERNAL_ERROR,
            startedAtMs = now,
            finishedAtMs = now,
            attempts = 0,
            detail = "execution state was unknown after Android process restart; command was not re-executed",
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
}
