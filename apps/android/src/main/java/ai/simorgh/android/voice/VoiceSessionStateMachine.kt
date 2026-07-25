package ai.simorgh.android.voice

import java.util.ArrayDeque

sealed interface VoiceEvent {
    val elapsedRealtimeMs: Long

    data class Arm(
        val activationMode: VoiceActivationMode,
        override val elapsedRealtimeMs: Long,
    ) : VoiceEvent

    data class Disarm(
        val reason: String,
        override val elapsedRealtimeMs: Long,
    ) : VoiceEvent

    data class AudioConflictChanged(
        val conflict: VoiceAudioConflict?,
        override val elapsedRealtimeMs: Long,
    ) : VoiceEvent

    data class WakeDetected(
        val detection: WakeDetection,
    ) : VoiceEvent {
        override val elapsedRealtimeMs: Long
            get() = detection.capturedAtElapsedRealtimeMs
    }

    data class PushToTalkStarted(
        val activationId: String,
        val inputMode: VoiceInputMode = VoiceInputMode.COMMAND,
        override val elapsedRealtimeMs: Long,
    ) : VoiceEvent

    data class CaptureCompleted(
        val sessionId: String,
        val audio: VoiceAudioReference,
        val contextTerms: List<VoiceContextTerm> = emptyList(),
        override val elapsedRealtimeMs: Long,
    ) : VoiceEvent

    data class AsrCompleted(
        val sessionId: String,
        val result: AsrResult,
        override val elapsedRealtimeMs: Long,
    ) : VoiceEvent

    data class TaskAccepted(
        val sessionId: String,
        val requestId: String,
        override val elapsedRealtimeMs: Long,
    ) : VoiceEvent

    data class TaskResultReady(
        val sessionId: String,
        val requestId: String,
        val responseText: String,
        val allowFollowUp: Boolean = false,
        override val elapsedRealtimeMs: Long,
    ) : VoiceEvent

    data class TaskFailed(
        val sessionId: String,
        val requestId: String,
        val detail: String,
        val userMessage: String? = null,
        override val elapsedRealtimeMs: Long,
    ) : VoiceEvent

    data class SpeechFinished(
        val sessionId: String,
        val requestId: String,
        override val elapsedRealtimeMs: Long,
    ) : VoiceEvent

    data class BargeIn(
        val activationId: String,
        override val elapsedRealtimeMs: Long,
    ) : VoiceEvent

    data class Cancel(
        val reason: String,
        override val elapsedRealtimeMs: Long,
    ) : VoiceEvent

    data class Failure(
        val detail: String,
        override val elapsedRealtimeMs: Long,
    ) : VoiceEvent

    data class Tick(
        override val elapsedRealtimeMs: Long,
    ) : VoiceEvent
}

sealed interface VoiceEffect {
    data class PauseWakeEngine(val reason: String) : VoiceEffect

    data class ResumeWakeEngine(val reason: String) : VoiceEffect

    data class StartCapture(
        val sessionId: String,
        val turnIndex: Int,
        val activationMode: VoiceActivationMode,
        val inputMode: VoiceInputMode,
        val deadlineElapsedRealtimeMs: Long,
    ) : VoiceEffect

    data class StopCapture(
        val sessionId: String,
        val reason: String,
    ) : VoiceEffect

    data class RequestTranscription(val request: AsrRequest) : VoiceEffect

    data class CancelTranscription(
        val requestId: String,
        val reason: String,
    ) : VoiceEffect

    data class SubmitTask(val task: VoiceTaskSubmission) : VoiceEffect

    data class CancelTask(
        val requestId: String,
        val reason: String,
    ) : VoiceEffect

    data class Speak(
        val request: TtsRequest,
        val purpose: VoiceSpeechPurpose,
    ) : VoiceEffect

    data class StopSpeaking(
        val requestId: String,
        val reason: String,
    ) : VoiceEffect

    data class RequestClarification(
        val sessionId: String,
        val reason: VoiceClarificationReason,
        val prompt: String,
    ) : VoiceEffect
}

enum class VoiceSpeechPurpose {
    RESPONSE,
    CLARIFICATION,
    FAILURE,
}

data class VoiceTransition(
    val accepted: Boolean,
    val reason: String,
    val previous: VoiceRuntimeSnapshot,
    val current: VoiceRuntimeSnapshot,
    val effects: List<VoiceEffect> = emptyList(),
)

/**
 * Pure deterministic controller. It emits typed effects but performs no microphone, network,
 * provider, model, Core, Accessibility, or Android side-effect call itself.
 */
class VoiceSessionStateMachine(
    private val wakeProfile: WakePhraseProfile,
    private val policy: VoiceRuntimePolicy = VoiceRuntimePolicy(),
) {
    private val seenDetectionIds = linkedSetOf<String>()
    private val detectionOrder = ArrayDeque<String>()
    private val normalizedWakePhrases = wakeProfile.phrases
        .map(PersianSpeechNormalizer::normalize)
        .map(NormalizedPersianSpeech::routingText)
        .toSet()

    private var state = VoiceRuntimeSnapshot()
    private var activeInputMode: VoiceInputMode = policy.inputMode
    private var postSpeechAction: PostSpeechAction = PostSpeechAction.NONE
    private var pendingSpeechOutcome: VoiceSessionOutcome? = null
    private var pendingSpeechDetail: String = ""

    fun snapshot(): VoiceRuntimeSnapshot = state

    fun dispatch(event: VoiceEvent): VoiceTransition {
        val previous = state
        if (event.elapsedRealtimeMs < state.lastEventElapsedRealtimeMs) {
            return VoiceTransition(
                accepted = false,
                reason = "voice event monotonic timestamp moved backwards",
                previous = previous,
                current = state,
            )
        }

        if (
            event !is VoiceEvent.Cancel &&
            event !is VoiceEvent.Disarm &&
            event !is VoiceEvent.AudioConflictChanged
        ) {
            expirationReason(event.elapsedRealtimeMs)?.let { reason ->
                return finishSession(
                    atElapsedRealtimeMs = event.elapsedRealtimeMs,
                    outcome = VoiceSessionOutcome.TIMED_OUT,
                    detail = reason,
                    cancelExternalWork = true,
                )
            }
        }

        return when (event) {
            is VoiceEvent.Arm -> arm(event)
            is VoiceEvent.Disarm -> disarm(event)
            is VoiceEvent.AudioConflictChanged -> changeAudioConflict(event)
            is VoiceEvent.WakeDetected -> acceptWake(event)
            is VoiceEvent.PushToTalkStarted -> startPushToTalk(event)
            is VoiceEvent.CaptureCompleted -> completeCapture(event)
            is VoiceEvent.AsrCompleted -> completeAsr(event)
            is VoiceEvent.TaskAccepted -> acceptTask(event)
            is VoiceEvent.TaskResultReady -> receiveTaskResult(event)
            is VoiceEvent.TaskFailed -> failTask(event)
            is VoiceEvent.SpeechFinished -> finishSpeech(event)
            is VoiceEvent.BargeIn -> bargeIn(event)
            is VoiceEvent.Cancel -> cancel(event)
            is VoiceEvent.Failure -> finishSession(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                outcome = VoiceSessionOutcome.FAILED,
                detail = event.detail.take(MAX_DETAIL_LENGTH),
                cancelExternalWork = true,
            )
            is VoiceEvent.Tick -> noOp(
                event.elapsedRealtimeMs,
                "voice runtime remains within all active deadlines",
            )
        }
    }

    private fun arm(event: VoiceEvent.Arm): VoiceTransition {
        require(event.elapsedRealtimeMs >= 0)
        if (
            event.activationMode != VoiceActivationMode.ASSISTANT_ROLE_WAKE &&
            event.activationMode != VoiceActivationMode.FOREGROUND_WAKE
        ) {
            return reject(
                event.elapsedRealtimeMs,
                "armed wake mode must be assistant-role or foreground wake",
            )
        }
        if (state.activeSessionId != null) {
            return reject(
                event.elapsedRealtimeMs,
                "cannot re-arm wake while a voice session is active",
            )
        }
        val shouldPause = state.audioConflict != null
        val next = state.copy(
            armed = true,
            phase = VoiceSessionPhase.ARMED,
            configuredActivationMode = event.activationMode,
            wakePaused = shouldPause,
            lastEventElapsedRealtimeMs = event.elapsedRealtimeMs,
            lastDetail = if (shouldPause) {
                "wake armed but paused by ${state.audioConflict}"
            } else {
                "wake engine armed"
            },
        )
        val effects = if (shouldPause) {
            emptyList()
        } else {
            listOf(VoiceEffect.ResumeWakeEngine("voice runtime armed"))
        }
        return apply(
            next = next,
            effects = effects,
            reason = next.lastDetail,
        )
    }

    private fun disarm(event: VoiceEvent.Disarm): VoiceTransition {
        require(event.elapsedRealtimeMs >= 0)
        val previous = state
        val effects = mutableListOf<VoiceEffect>()
        collectStopEffects(
            destination = effects,
            reason = event.reason.ifBlank { "voice runtime disarmed" },
            cancelExternalWork = true,
        )
        state = VoiceRuntimeSnapshot(
            armed = false,
            phase = VoiceSessionPhase.DISARMED,
            configuredActivationMode = null,
            wakePaused = true,
            audioConflict = previous.audioConflict,
            lastEventElapsedRealtimeMs = event.elapsedRealtimeMs,
            cooldownUntilElapsedRealtimeMs = previous.cooldownUntilElapsedRealtimeMs,
            lastOutcome = if (previous.activeSessionId == null) {
                previous.lastOutcome
            } else {
                VoiceSessionOutcome.CANCELLED
            },
            lastDetail = event.reason.take(MAX_DETAIL_LENGTH),
        )
        clearPendingSpeech()
        return VoiceTransition(
            accepted = true,
            reason = "voice runtime disarmed",
            previous = previous,
            current = state,
            effects = effects,
        )
    }

    private fun changeAudioConflict(
        event: VoiceEvent.AudioConflictChanged,
    ): VoiceTransition {
        require(event.elapsedRealtimeMs >= 0)
        if (event.conflict != null && state.activeSessionId != null) {
            val transition = finishSession(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                outcome = VoiceSessionOutcome.BLOCKED,
                detail = "audio session interrupted by ${event.conflict}",
                cancelExternalWork = true,
                resumeWake = false,
            )
            val previous = transition.previous
            state = transition.current.copy(
                audioConflict = event.conflict,
                wakePaused = true,
            )
            return transition.copy(current = state)
        }

        val previous = state
        val effects = mutableListOf<VoiceEffect>()
        val nextWakePaused = when {
            !state.armed -> true
            event.conflict != null -> true
            state.activeSessionId != null -> true
            else -> false
        }
        if (state.armed && state.activeSessionId == null) {
            if (event.conflict != null && !state.wakePaused) {
                effects += VoiceEffect.PauseWakeEngine(
                    "audio conflict ${event.conflict}",
                )
            } else if (event.conflict == null && state.wakePaused) {
                effects += VoiceEffect.ResumeWakeEngine("audio conflict cleared")
            }
        }
        state = state.copy(
            audioConflict = event.conflict,
            wakePaused = nextWakePaused,
            lastEventElapsedRealtimeMs = event.elapsedRealtimeMs,
            lastDetail = event.conflict?.let { "audio conflict: $it" }
                ?: "audio conflict cleared",
        )
        return VoiceTransition(
            accepted = true,
            reason = state.lastDetail,
            previous = previous,
            current = state,
            effects = effects,
        )
    }

    private fun acceptWake(event: VoiceEvent.WakeDetected): VoiceTransition {
        val detection = event.detection
        if (detection.profileId != wakeProfile.profileId) {
            return reject(
                event.elapsedRealtimeMs,
                "wake detection belongs to another phrase profile",
            )
        }
        if (!recordDetection(detection.detectionId)) {
            return reject(
                event.elapsedRealtimeMs,
                "duplicate wake detection was ignored",
            )
        }
        if (!state.armed || state.phase != VoiceSessionPhase.ARMED) {
            return reject(
                event.elapsedRealtimeMs,
                "wake detection arrived while runtime was not idle and armed",
            )
        }
        if (state.wakePaused || state.audioConflict != null) {
            return reject(
                event.elapsedRealtimeMs,
                "wake detection arrived while wake processing was paused",
            )
        }
        if (event.elapsedRealtimeMs < state.cooldownUntilElapsedRealtimeMs) {
            return reject(
                event.elapsedRealtimeMs,
                "wake detection was inside the cooldown window",
            )
        }
        if (detection.confidenceBps < wakeProfile.minimumConfidenceBps) {
            return reject(
                event.elapsedRealtimeMs,
                "wake confidence was below the configured threshold",
            )
        }
        val normalizedPhrase = PersianSpeechNormalizer.normalize(detection.phrase).routingText
        if (normalizedPhrase !in normalizedWakePhrases) {
            return reject(
                event.elapsedRealtimeMs,
                "wake engine reported a phrase outside the active profile",
            )
        }
        val activationMode = state.configuredActivationMode
            ?: return reject(
                event.elapsedRealtimeMs,
                "wake runtime has no configured activation mode",
            )
        return startSession(
            activationMode = activationMode,
            activationId = detection.detectionId,
            profileId = wakeProfile.profileId,
            inputMode = policy.inputMode,
            atElapsedRealtimeMs = event.elapsedRealtimeMs,
            reason = "local wake phrase accepted",
        )
    }

    private fun startPushToTalk(
        event: VoiceEvent.PushToTalkStarted,
    ): VoiceTransition {
        require(event.activationId.isNotBlank() && event.activationId.length <= 256)
        if (state.activeSessionId != null) {
            return reject(
                event.elapsedRealtimeMs,
                "push-to-talk cannot replace an active voice session",
            )
        }
        if (state.audioConflict != null) {
            return reject(
                event.elapsedRealtimeMs,
                "push-to-talk blocked by audio conflict ${state.audioConflict}",
            )
        }
        return startSession(
            activationMode = VoiceActivationMode.PUSH_TO_TALK,
            activationId = event.activationId,
            profileId = "push-to-talk",
            inputMode = event.inputMode,
            atElapsedRealtimeMs = event.elapsedRealtimeMs,
            reason = "explicit push-to-talk accepted",
        )
    }

    private fun startSession(
        activationMode: VoiceActivationMode,
        activationId: String,
        profileId: String,
        inputMode: VoiceInputMode,
        atElapsedRealtimeMs: Long,
        reason: String,
    ): VoiceTransition {
        val previous = state
        val sessionId = VoiceIdentity.sessionId(
            activationMode = activationMode,
            profileId = profileId,
            activationId = activationId,
        )
        val sessionDeadline = saturatingAdd(
            atElapsedRealtimeMs,
            policy.maximumSessionDurationMs,
        )
        val captureDeadline = minOf(
            sessionDeadline,
            saturatingAdd(atElapsedRealtimeMs, policy.captureTimeoutMs),
        )
        activeInputMode = inputMode
        clearPendingSpeech()
        state = state.copy(
            phase = VoiceSessionPhase.CAPTURING,
            activeActivationMode = activationMode,
            activeSessionId = sessionId,
            activeActivationId = activationId,
            activeAsrRequestId = null,
            activeTaskRequestId = null,
            activeTtsRequestId = null,
            turnIndex = 0,
            wakePaused = true,
            lastEventElapsedRealtimeMs = atElapsedRealtimeMs,
            cooldownUntilElapsedRealtimeMs = saturatingAdd(
                atElapsedRealtimeMs,
                wakeProfile.cooldownMs,
            ),
            sessionStartedAtElapsedRealtimeMs = atElapsedRealtimeMs,
            sessionDeadlineElapsedRealtimeMs = sessionDeadline,
            phaseDeadlineElapsedRealtimeMs = captureDeadline,
            followUpUntilElapsedRealtimeMs = null,
            normalizedTranscript = null,
            lastOutcome = null,
            lastDetail = reason,
        )
        val effects = buildList {
            if (previous.armed && !previous.wakePaused) {
                add(VoiceEffect.PauseWakeEngine("voice session active"))
            }
            add(
                VoiceEffect.StartCapture(
                    sessionId = sessionId,
                    turnIndex = 0,
                    activationMode = activationMode,
                    inputMode = inputMode,
                    deadlineElapsedRealtimeMs = captureDeadline,
                )
            )
        }
        return VoiceTransition(
            accepted = true,
            reason = reason,
            previous = previous,
            current = state,
            effects = effects,
        )
    }

    private fun completeCapture(
        event: VoiceEvent.CaptureCompleted,
    ): VoiceTransition {
        val sessionId = state.activeSessionId
            ?: return reject(event.elapsedRealtimeMs, "capture completed without a session")
        if (event.sessionId != sessionId) {
            return reject(event.elapsedRealtimeMs, "capture belongs to another voice session")
        }
        if (
            state.phase != VoiceSessionPhase.CAPTURING &&
            state.phase != VoiceSessionPhase.FOLLOW_UP
        ) {
            return reject(event.elapsedRealtimeMs, "capture completed in an invalid phase")
        }
        if (
            event.audio.startedAtElapsedRealtimeMs <
            requireNotNull(state.sessionStartedAtElapsedRealtimeMs) ||
            event.audio.finishedAtElapsedRealtimeMs > event.elapsedRealtimeMs ||
            event.audio.durationMs > policy.captureTimeoutMs
        ) {
            return finishSession(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                outcome = VoiceSessionOutcome.BLOCKED,
                detail = "captured audio violated monotonic session bounds",
                cancelExternalWork = true,
            )
        }
        val hardDeadline = requireNotNull(state.sessionDeadlineElapsedRealtimeMs)
        val transcriptionDeadline = minOf(
            hardDeadline,
            saturatingAdd(event.elapsedRealtimeMs, policy.transcriptionTimeoutMs),
        )
        val remaining = transcriptionDeadline - event.elapsedRealtimeMs
        if (remaining < MINIMUM_EXTERNAL_BUDGET_MS) {
            return finishSession(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                outcome = VoiceSessionOutcome.TIMED_OUT,
                detail = "insufficient monotonic budget remained for transcription",
                cancelExternalWork = true,
            )
        }
        val requestId = VoiceIdentity.asrRequestId(
            sessionId = sessionId,
            turnIndex = state.turnIndex,
            audioReferenceId = event.audio.referenceId,
        )
        val request = AsrRequest(
            requestId = requestId,
            sessionId = sessionId,
            turnIndex = state.turnIndex,
            audio = event.audio,
            locale = policy.locale,
            mode = activeInputMode,
            privacyMode = policy.privacyMode,
            contextTerms = event.contextTerms,
            maximumLatencyMs = minOf(policy.transcriptionTimeoutMs, remaining),
            maximumCloudCalls = policy.maximumCloudAsrCalls,
        )
        val previous = state
        state = state.copy(
            phase = VoiceSessionPhase.TRANSCRIBING,
            activeAsrRequestId = requestId,
            phaseDeadlineElapsedRealtimeMs = transcriptionDeadline,
            lastEventElapsedRealtimeMs = event.elapsedRealtimeMs,
            lastDetail = "captured speech is ready for ASR",
        )
        return VoiceTransition(
            accepted = true,
            reason = state.lastDetail,
            previous = previous,
            current = state,
            effects = listOf(
                VoiceEffect.StopCapture(sessionId, "capture completed"),
                VoiceEffect.RequestTranscription(request),
            ),
        )
    }

    private fun completeAsr(event: VoiceEvent.AsrCompleted): VoiceTransition {
        val sessionId = state.activeSessionId
            ?: return reject(event.elapsedRealtimeMs, "ASR completed without a session")
        if (
            event.sessionId != sessionId ||
            event.result.sessionId != sessionId ||
            event.result.requestId != state.activeAsrRequestId ||
            event.result.turnIndex != state.turnIndex
        ) {
            return reject(event.elapsedRealtimeMs, "ASR result identity does not match session")
        }
        if (state.phase != VoiceSessionPhase.TRANSCRIBING) {
            return reject(event.elapsedRealtimeMs, "ASR result arrived outside transcription")
        }
        if (event.result.producedAtElapsedRealtimeMs > event.elapsedRealtimeMs) {
            return finishSession(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                outcome = VoiceSessionOutcome.BLOCKED,
                detail = "ASR result monotonic timestamp is in the future",
                cancelExternalWork = true,
            )
        }

        val normalized = PersianSpeechNormalizer.normalize(event.result.transcript)
        if (
            event.result.confidenceBps >= policy.cancellationMinimumConfidenceBps &&
            normalized.cancellationCommand
        ) {
            return finishSession(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                outcome = VoiceSessionOutcome.CANCELLED,
                detail = "spoken cancellation command accepted",
                cancelExternalWork = true,
            )
        }
        if (normalized.routingText.isEmpty()) {
            return requestClarification(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                reason = VoiceClarificationReason.EMPTY_TRANSCRIPT,
                prompt = "صدای قابل فهمی دریافت نکردم. لطفاً دوباره بگویید.",
                normalizedTranscript = normalized.routingText,
            )
        }
        if (event.result.confidenceBps < policy.asrMinimumConfidenceBps) {
            return requestClarification(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                reason = VoiceClarificationReason.LOW_CONFIDENCE,
                prompt = "از جمله مطمئن نشدم. لطفاً کوتاه‌تر و واضح‌تر تکرار کنید.",
                normalizedTranscript = normalized.routingText,
            )
        }
        val sensitiveAmbiguity = event.result.ambiguities.firstOrNull { ambiguity ->
            ambiguity.sensitive &&
                ambiguity.confidenceBps < policy.sensitiveEntityMinimumConfidenceBps
        }
        if (sensitiveAmbiguity != null) {
            return requestClarification(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                reason = VoiceClarificationReason.SENSITIVE_ENTITY,
                prompt = "برای بخش حساس «${sensitiveAmbiguity.surfaceText}» نیاز به تأیید دارم.",
                normalizedTranscript = normalized.routingText,
            )
        }
        val ambiguity = event.result.ambiguities.firstOrNull { value ->
            value.confidenceBps < policy.asrMinimumConfidenceBps
        }
        if (ambiguity != null) {
            return requestClarification(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                reason = VoiceClarificationReason.AMBIGUOUS_ENTITY,
                prompt = "منظور از «${ambiguity.surfaceText}» را دقیق‌تر بگویید.",
                normalizedTranscript = normalized.routingText,
            )
        }

        val taskRequestId = VoiceIdentity.taskRequestId(
            sessionId = sessionId,
            turnIndex = state.turnIndex,
            asrResultId = event.result.resultId,
            normalizedTranscript = normalized.routingText,
        )
        val hardDeadline = requireNotNull(state.sessionDeadlineElapsedRealtimeMs)
        val routingDeadline = minOf(
            hardDeadline,
            saturatingAdd(event.elapsedRealtimeMs, policy.routingTimeoutMs),
        )
        val previous = state
        state = state.copy(
            phase = VoiceSessionPhase.ROUTING,
            activeAsrRequestId = null,
            activeTaskRequestId = taskRequestId,
            normalizedTranscript = normalized.routingText,
            phaseDeadlineElapsedRealtimeMs = routingDeadline,
            lastEventElapsedRealtimeMs = event.elapsedRealtimeMs,
            lastDetail = "high-confidence transcript is ready for specialist routing",
        )
        return VoiceTransition(
            accepted = true,
            reason = state.lastDetail,
            previous = previous,
            current = state,
            effects = listOf(
                VoiceEffect.SubmitTask(
                    VoiceTaskSubmission(
                        requestId = taskRequestId,
                        sessionId = sessionId,
                        turnIndex = state.turnIndex,
                        originalTranscript = event.result.transcript,
                        normalizedTranscript = normalized.routingText,
                        locale = event.result.locale,
                        activationMode = requireNotNull(state.activeActivationMode),
                        asrConfidenceBps = event.result.confidenceBps,
                        receivedAtElapsedRealtimeMs = event.elapsedRealtimeMs,
                    )
                )
            ),
        )
    }

    private fun requestClarification(
        atElapsedRealtimeMs: Long,
        reason: VoiceClarificationReason,
        prompt: String,
        normalizedTranscript: String,
    ): VoiceTransition {
        val sessionId = requireNotNull(state.activeSessionId)
        val taskIdentity = state.activeAsrRequestId ?: "clarification"
        val ttsRequestId = VoiceIdentity.ttsRequestId(
            sessionId = sessionId,
            taskRequestId = taskIdentity,
            text = prompt,
        )
        val previous = state
        postSpeechAction = PostSpeechAction.START_CLARIFICATION_CAPTURE
        pendingSpeechOutcome = null
        pendingSpeechDetail = ""
        state = state.copy(
            phase = VoiceSessionPhase.SPEAKING,
            activeAsrRequestId = null,
            activeTtsRequestId = ttsRequestId,
            normalizedTranscript = normalizedTranscript,
            phaseDeadlineElapsedRealtimeMs = state.sessionDeadlineElapsedRealtimeMs,
            lastEventElapsedRealtimeMs = atElapsedRealtimeMs,
            lastDetail = "clarification required: $reason",
        )
        return VoiceTransition(
            accepted = true,
            reason = state.lastDetail,
            previous = previous,
            current = state,
            effects = listOf(
                VoiceEffect.RequestClarification(
                    sessionId = sessionId,
                    reason = reason,
                    prompt = prompt,
                ),
                VoiceEffect.Speak(
                    request = TtsRequest(
                        requestId = ttsRequestId,
                        sessionId = sessionId,
                        text = prompt,
                        profile = policy.ttsProfile,
                    ),
                    purpose = VoiceSpeechPurpose.CLARIFICATION,
                ),
            ),
        )
    }

    private fun acceptTask(event: VoiceEvent.TaskAccepted): VoiceTransition {
        if (!matchesActiveTask(event.sessionId, event.requestId)) {
            return reject(event.elapsedRealtimeMs, "task ACK does not match voice session")
        }
        if (state.phase != VoiceSessionPhase.ROUTING) {
            return reject(event.elapsedRealtimeMs, "task ACK arrived in an invalid phase")
        }
        val previous = state
        state = state.copy(
            phase = VoiceSessionPhase.WAITING_FOR_RESULT,
            lastEventElapsedRealtimeMs = event.elapsedRealtimeMs,
            lastDetail = "specialist task accepted",
        )
        return VoiceTransition(
            accepted = true,
            reason = state.lastDetail,
            previous = previous,
            current = state,
        )
    }

    private fun receiveTaskResult(
        event: VoiceEvent.TaskResultReady,
    ): VoiceTransition {
        if (!matchesActiveTask(event.sessionId, event.requestId)) {
            return reject(event.elapsedRealtimeMs, "task result does not match voice session")
        }
        if (
            state.phase != VoiceSessionPhase.ROUTING &&
            state.phase != VoiceSessionPhase.WAITING_FOR_RESULT
        ) {
            return reject(event.elapsedRealtimeMs, "task result arrived in an invalid phase")
        }
        if (event.responseText.isBlank() || event.responseText.length > 100_000) {
            return finishSession(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                outcome = VoiceSessionOutcome.BLOCKED,
                detail = "task response violated TTS text contract",
                cancelExternalWork = false,
            )
        }
        val sessionId = requireNotNull(state.activeSessionId)
        val ttsRequestId = VoiceIdentity.ttsRequestId(
            sessionId = sessionId,
            taskRequestId = event.requestId,
            text = event.responseText,
        )
        val previous = state
        postSpeechAction = if (event.allowFollowUp && policy.followUpWindowMs > 0) {
            PostSpeechAction.START_FOLLOW_UP_CAPTURE
        } else {
            PostSpeechAction.FINISH
        }
        pendingSpeechOutcome = VoiceSessionOutcome.SUCCEEDED
        pendingSpeechDetail = "specialist response delivered"
        state = state.copy(
            phase = VoiceSessionPhase.SPEAKING,
            activeTtsRequestId = ttsRequestId,
            phaseDeadlineElapsedRealtimeMs = state.sessionDeadlineElapsedRealtimeMs,
            lastEventElapsedRealtimeMs = event.elapsedRealtimeMs,
            lastDetail = "specialist response ready for Persian TTS",
        )
        return VoiceTransition(
            accepted = true,
            reason = state.lastDetail,
            previous = previous,
            current = state,
            effects = listOf(
                VoiceEffect.Speak(
                    request = TtsRequest(
                        requestId = ttsRequestId,
                        sessionId = sessionId,
                        text = event.responseText,
                        profile = policy.ttsProfile,
                    ),
                    purpose = VoiceSpeechPurpose.RESPONSE,
                )
            ),
        )
    }

    private fun failTask(event: VoiceEvent.TaskFailed): VoiceTransition {
        if (!matchesActiveTask(event.sessionId, event.requestId)) {
            return reject(event.elapsedRealtimeMs, "task failure does not match voice session")
        }
        val userMessage = event.userMessage?.takeIf(String::isNotBlank)
        if (userMessage == null) {
            return finishSession(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                outcome = VoiceSessionOutcome.FAILED,
                detail = event.detail.take(MAX_DETAIL_LENGTH),
                cancelExternalWork = false,
            )
        }
        val sessionId = requireNotNull(state.activeSessionId)
        val ttsRequestId = VoiceIdentity.ttsRequestId(
            sessionId = sessionId,
            taskRequestId = event.requestId,
            text = userMessage,
        )
        val previous = state
        postSpeechAction = PostSpeechAction.FINISH
        pendingSpeechOutcome = VoiceSessionOutcome.FAILED
        pendingSpeechDetail = event.detail.take(MAX_DETAIL_LENGTH)
        state = state.copy(
            phase = VoiceSessionPhase.SPEAKING,
            activeTtsRequestId = ttsRequestId,
            lastEventElapsedRealtimeMs = event.elapsedRealtimeMs,
            lastDetail = "task failure is ready for spoken explanation",
        )
        return VoiceTransition(
            accepted = true,
            reason = state.lastDetail,
            previous = previous,
            current = state,
            effects = listOf(
                VoiceEffect.Speak(
                    request = TtsRequest(
                        requestId = ttsRequestId,
                        sessionId = sessionId,
                        text = userMessage,
                        profile = policy.ttsProfile,
                    ),
                    purpose = VoiceSpeechPurpose.FAILURE,
                )
            ),
        )
    }

    private fun finishSpeech(event: VoiceEvent.SpeechFinished): VoiceTransition {
        if (
            state.phase != VoiceSessionPhase.SPEAKING ||
            event.sessionId != state.activeSessionId ||
            event.requestId != state.activeTtsRequestId
        ) {
            return reject(event.elapsedRealtimeMs, "TTS completion does not match session")
        }
        return when (postSpeechAction) {
            PostSpeechAction.START_CLARIFICATION_CAPTURE -> startNextCapture(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                incrementTurn = false,
                activationMode = requireNotNull(state.activeActivationMode),
                inputMode = VoiceInputMode.COMMAND,
                phase = VoiceSessionPhase.CAPTURING,
                reason = "listening for clarified Persian command",
            )
            PostSpeechAction.START_FOLLOW_UP_CAPTURE -> startNextCapture(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                incrementTurn = true,
                activationMode = VoiceActivationMode.FOLLOW_UP,
                inputMode = VoiceInputMode.CONVERSATION,
                phase = VoiceSessionPhase.FOLLOW_UP,
                reason = "bounded follow-up listening window started",
            )
            PostSpeechAction.FINISH -> finishSession(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                outcome = pendingSpeechOutcome ?: VoiceSessionOutcome.SUCCEEDED,
                detail = pendingSpeechDetail.ifBlank { "voice response completed" },
                cancelExternalWork = false,
            )
            PostSpeechAction.NONE -> finishSession(
                atElapsedRealtimeMs = event.elapsedRealtimeMs,
                outcome = VoiceSessionOutcome.FAILED,
                detail = "TTS completed without a post-speech action",
                cancelExternalWork = false,
            )
        }
    }

    private fun bargeIn(event: VoiceEvent.BargeIn): VoiceTransition {
        require(event.activationId.isNotBlank() && event.activationId.length <= 256)
        if (state.phase != VoiceSessionPhase.SPEAKING) {
            return reject(event.elapsedRealtimeMs, "barge-in requires active TTS")
        }
        val ttsRequestId = state.activeTtsRequestId
            ?: return reject(event.elapsedRealtimeMs, "barge-in has no TTS identity")
        val transition = startNextCapture(
            atElapsedRealtimeMs = event.elapsedRealtimeMs,
            incrementTurn = true,
            activationMode = VoiceActivationMode.FOLLOW_UP,
            inputMode = VoiceInputMode.CONVERSATION,
            phase = VoiceSessionPhase.FOLLOW_UP,
            reason = "user interrupted TTS and started a follow-up turn",
        )
        return transition.copy(
            effects = listOf(
                VoiceEffect.StopSpeaking(ttsRequestId, "user barge-in"),
            ) + transition.effects,
        )
    }

    private fun startNextCapture(
        atElapsedRealtimeMs: Long,
        incrementTurn: Boolean,
        activationMode: VoiceActivationMode,
        inputMode: VoiceInputMode,
        phase: VoiceSessionPhase,
        reason: String,
    ): VoiceTransition {
        val sessionId = requireNotNull(state.activeSessionId)
        val hardDeadline = requireNotNull(state.sessionDeadlineElapsedRealtimeMs)
        val followUpDeadline = if (phase == VoiceSessionPhase.FOLLOW_UP) {
            minOf(
                hardDeadline,
                saturatingAdd(atElapsedRealtimeMs, policy.followUpWindowMs),
            )
        } else {
            hardDeadline
        }
        val captureDeadline = minOf(
            followUpDeadline,
            saturatingAdd(atElapsedRealtimeMs, policy.captureTimeoutMs),
        )
        if (captureDeadline - atElapsedRealtimeMs < MINIMUM_EXTERNAL_BUDGET_MS) {
            return finishSession(
                atElapsedRealtimeMs = atElapsedRealtimeMs,
                outcome = VoiceSessionOutcome.TIMED_OUT,
                detail = "insufficient budget remained for another voice turn",
                cancelExternalWork = false,
            )
        }
        val nextTurn = if (incrementTurn) state.turnIndex + 1 else state.turnIndex
        val previous = state
        activeInputMode = inputMode
        clearPendingSpeech()
        state = state.copy(
            phase = phase,
            activeActivationMode = activationMode,
            activeActivationId = if (incrementTurn) {
                "follow-up-$nextTurn"
            } else {
                state.activeActivationId
            },
            activeAsrRequestId = null,
            activeTaskRequestId = null,
            activeTtsRequestId = null,
            turnIndex = nextTurn,
            phaseDeadlineElapsedRealtimeMs = captureDeadline,
            followUpUntilElapsedRealtimeMs = if (phase == VoiceSessionPhase.FOLLOW_UP) {
                followUpDeadline
            } else {
                null
            },
            normalizedTranscript = null,
            lastEventElapsedRealtimeMs = atElapsedRealtimeMs,
            lastDetail = reason,
        )
        return VoiceTransition(
            accepted = true,
            reason = reason,
            previous = previous,
            current = state,
            effects = listOf(
                VoiceEffect.StartCapture(
                    sessionId = sessionId,
                    turnIndex = nextTurn,
                    activationMode = activationMode,
                    inputMode = inputMode,
                    deadlineElapsedRealtimeMs = captureDeadline,
                )
            ),
        )
    }

    private fun cancel(event: VoiceEvent.Cancel): VoiceTransition {
        if (state.activeSessionId == null) {
            return reject(event.elapsedRealtimeMs, "no active voice session to cancel")
        }
        return finishSession(
            atElapsedRealtimeMs = event.elapsedRealtimeMs,
            outcome = VoiceSessionOutcome.CANCELLED,
            detail = event.reason.ifBlank { "voice session cancelled" },
            cancelExternalWork = true,
        )
    }

    private fun finishSession(
        atElapsedRealtimeMs: Long,
        outcome: VoiceSessionOutcome,
        detail: String,
        cancelExternalWork: Boolean,
        resumeWake: Boolean = true,
    ): VoiceTransition {
        val previous = state
        val effects = mutableListOf<VoiceEffect>()
        collectStopEffects(
            destination = effects,
            reason = detail,
            cancelExternalWork = cancelExternalWork,
        )
        val shouldResumeWake = resumeWake &&
            state.armed &&
            state.audioConflict == null
        if (shouldResumeWake) {
            effects += VoiceEffect.ResumeWakeEngine("voice session completed")
        }
        state = VoiceRuntimeSnapshot(
            armed = previous.armed,
            phase = if (previous.armed) {
                VoiceSessionPhase.ARMED
            } else {
                VoiceSessionPhase.DISARMED
            },
            configuredActivationMode = previous.configuredActivationMode,
            wakePaused = !shouldResumeWake,
            audioConflict = previous.audioConflict,
            lastEventElapsedRealtimeMs = atElapsedRealtimeMs,
            cooldownUntilElapsedRealtimeMs = previous.cooldownUntilElapsedRealtimeMs,
            lastOutcome = outcome,
            lastDetail = detail.take(MAX_DETAIL_LENGTH),
        )
        clearPendingSpeech()
        return VoiceTransition(
            accepted = true,
            reason = state.lastDetail,
            previous = previous,
            current = state,
            effects = effects,
        )
    }

    private fun collectStopEffects(
        destination: MutableList<VoiceEffect>,
        reason: String,
        cancelExternalWork: Boolean,
    ) {
        val sessionId = state.activeSessionId ?: return
        if (
            state.phase == VoiceSessionPhase.CAPTURING ||
            state.phase == VoiceSessionPhase.FOLLOW_UP
        ) {
            destination += VoiceEffect.StopCapture(sessionId, reason)
        }
        state.activeAsrRequestId?.let { requestId ->
            destination += VoiceEffect.CancelTranscription(requestId, reason)
        }
        state.activeTtsRequestId?.let { requestId ->
            destination += VoiceEffect.StopSpeaking(requestId, reason)
        }
        if (cancelExternalWork) {
            state.activeTaskRequestId?.let { requestId ->
                destination += VoiceEffect.CancelTask(requestId, reason)
            }
        }
    }

    private fun expirationReason(atElapsedRealtimeMs: Long): String? {
        if (state.activeSessionId == null) {
            return null
        }
        state.sessionDeadlineElapsedRealtimeMs?.let { deadline ->
            if (atElapsedRealtimeMs >= deadline) {
                return "voice session exceeded its hard monotonic deadline"
            }
        }
        state.phaseDeadlineElapsedRealtimeMs?.let { deadline ->
            if (atElapsedRealtimeMs >= deadline) {
                return "voice phase ${state.phase} exceeded its monotonic deadline"
            }
        }
        return null
    }

    private fun matchesActiveTask(sessionId: String, requestId: String): Boolean =
        sessionId == state.activeSessionId && requestId == state.activeTaskRequestId

    private fun recordDetection(detectionId: String): Boolean {
        if (!seenDetectionIds.add(detectionId)) {
            return false
        }
        detectionOrder.addLast(detectionId)
        while (detectionOrder.size > wakeProfile.maximumDetectionHistory) {
            val removed = detectionOrder.removeFirst()
            seenDetectionIds.remove(removed)
        }
        return true
    }

    private fun reject(
        atElapsedRealtimeMs: Long,
        reason: String,
    ): VoiceTransition {
        val previous = state
        state = state.copy(
            lastEventElapsedRealtimeMs = atElapsedRealtimeMs,
            lastDetail = reason.take(MAX_DETAIL_LENGTH),
        )
        return VoiceTransition(
            accepted = false,
            reason = state.lastDetail,
            previous = previous,
            current = state,
        )
    }

    private fun noOp(
        atElapsedRealtimeMs: Long,
        reason: String,
    ): VoiceTransition {
        val previous = state
        state = state.copy(
            lastEventElapsedRealtimeMs = atElapsedRealtimeMs,
            lastDetail = reason,
        )
        return VoiceTransition(
            accepted = true,
            reason = reason,
            previous = previous,
            current = state,
        )
    }

    private fun apply(
        next: VoiceRuntimeSnapshot,
        effects: List<VoiceEffect>,
        reason: String,
    ): VoiceTransition {
        val previous = state
        state = next
        return VoiceTransition(
            accepted = true,
            reason = reason,
            previous = previous,
            current = state,
            effects = effects,
        )
    }

    private fun clearPendingSpeech() {
        postSpeechAction = PostSpeechAction.NONE
        pendingSpeechOutcome = null
        pendingSpeechDetail = ""
    }

    private enum class PostSpeechAction {
        NONE,
        START_CLARIFICATION_CAPTURE,
        START_FOLLOW_UP_CAPTURE,
        FINISH,
    }

    private companion object {
        const val MAX_DETAIL_LENGTH = 2_000
        const val MINIMUM_EXTERNAL_BUDGET_MS = 100L

        fun saturatingAdd(left: Long, right: Long): Long = when {
            right > 0 && left > Long.MAX_VALUE - right -> Long.MAX_VALUE
            right < 0 && left < Long.MIN_VALUE - right -> Long.MIN_VALUE
            else -> left + right
        }
    }
}
