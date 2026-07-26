package ai.simorgh.android.voice

import java.io.Closeable
import java.nio.charset.StandardCharsets
import java.util.UUID

/** How one local voice session became authorized to capture speech. */
enum class VoiceActivationMode {
    ASSISTANT_ROLE_WAKE,
    FOREGROUND_WAKE,
    PUSH_TO_TALK,
    FOLLOW_UP,
}

enum class VoiceInputMode {
    COMMAND,
    DICTATION,
    CONVERSATION,
}

enum class VoicePrivacyMode {
    LOCAL_ONLY,
    CORE_ALLOWED,
    CLOUD_ASR_ALLOWED,
}

enum class VoiceSessionPhase {
    DISARMED,
    ARMED,
    CAPTURING,
    TRANSCRIBING,
    AWAITING_CLARIFICATION,
    ROUTING,
    WAITING_FOR_RESULT,
    SPEAKING,
    FOLLOW_UP,
}

enum class VoiceSessionOutcome {
    SUCCEEDED,
    CANCELLED,
    TIMED_OUT,
    BLOCKED,
    FAILED,
}

enum class VoiceAudioConflict {
    PHONE_CALL,
    OTHER_RECORDING,
    AUDIO_FOCUS_LOST,
    MICROPHONE_PERMISSION_REVOKED,
    SYSTEM_RESTRICTION,
}

enum class VoiceClarificationReason {
    EMPTY_TRANSCRIPT,
    LOW_CONFIDENCE,
    AMBIGUOUS_ENTITY,
    SENSITIVE_ENTITY,
    CONTRACT_INVALID,
}

enum class VoiceContextKind {
    REPOSITORY,
    APPLICATION,
    PERSON,
    ORGANIZATION,
    PRODUCT,
    TECHNICAL_TERM,
    CUSTOM,
}

data class PcmAudioFormat(
    val sampleRateHz: Int,
    val channelCount: Int = 1,
    val bitsPerSample: Int = 16,
) {
    init {
        require(sampleRateHz in 8_000..48_000) {
            "sampleRateHz must be in 8000..48000"
        }
        require(channelCount in 1..2) {
            "channelCount must be mono or stereo"
        }
        require(bitsPerSample in setOf(16, 24, 32)) {
            "bitsPerSample must be 16, 24, or 32"
        }
    }
}

data class PcmAudioFrame(
    val sequence: Long,
    val capturedAtElapsedRealtimeMs: Long,
    val pcm16: ShortArray,
) {
    init {
        require(sequence >= 0)
        require(capturedAtElapsedRealtimeMs >= 0)
        require(pcm16.isNotEmpty())
    }
}

data class WakeEngineDescriptor(
    val engineId: String,
    val version: String,
    val runsLocally: Boolean,
    val supportsCustomPhrases: Boolean,
) {
    init {
        require(engineId.isNotBlank() && engineId.length <= 128)
        require(version.isNotBlank() && version.length <= 64)
    }
}

data class WakePhraseProfile(
    val profileId: String,
    val phrases: Set<String>,
    val locale: String = "fa-IR",
    val minimumConfidenceBps: Int = 7_500,
    val cooldownMs: Long = 2_500,
    val maximumDetectionHistory: Int = 64,
) {
    init {
        require(profileId.isNotBlank() && profileId.length <= 128)
        require(phrases.isNotEmpty() && phrases.size <= 16)
        phrases.forEach { phrase ->
            require(phrase.isNotBlank() && phrase.length <= 128)
        }
        require(locale.isNotBlank() && locale.length <= 35)
        require(minimumConfidenceBps in 0..10_000)
        require(cooldownMs in 0..60_000)
        require(maximumDetectionHistory in 1..1_024)
    }
}

data class WakeDetection(
    val detectionId: String,
    val profileId: String,
    val phrase: String,
    val confidenceBps: Int,
    val capturedAtElapsedRealtimeMs: Long,
    val engineId: String,
    val engineVersion: String,
) {
    init {
        require(detectionId.isNotBlank() && detectionId.length <= 256)
        require(profileId.isNotBlank() && profileId.length <= 128)
        require(phrase.isNotBlank() && phrase.length <= 128)
        require(confidenceBps in 0..10_000)
        require(capturedAtElapsedRealtimeMs >= 0)
        require(engineId.isNotBlank() && engineId.length <= 128)
        require(engineVersion.isNotBlank() && engineVersion.length <= 64)
    }
}

enum class WakeEngineHealthState {
    STOPPED,
    READY,
    RUNNING,
    PAUSED,
    FAILED,
}

data class WakeEngineHealth(
    val state: WakeEngineHealthState,
    val detail: String = "",
    val processedFrames: Long = 0,
    val detections: Long = 0,
) {
    init {
        require(detail.length <= 1_000)
        require(processedFrames >= 0)
        require(detections >= 0)
    }
}

/**
 * Engine-neutral local wake interface. Implementations must not perform provider or Core calls.
 */
interface WakeEngine : Closeable {
    val descriptor: WakeEngineDescriptor

    fun start(
        format: PcmAudioFormat,
        profile: WakePhraseProfile,
    )

    fun process(frame: PcmAudioFrame): WakeDetection?

    fun pause(reason: String)

    fun resume()

    fun health(): WakeEngineHealth

    fun stop()

    override fun close() = stop()
}

data class VoiceAudioReference(
    /** Opaque in-process or encrypted-local reference; never raw PCM in a trace. */
    val referenceId: String,
    val startedAtElapsedRealtimeMs: Long,
    val finishedAtElapsedRealtimeMs: Long,
    val durationMs: Long,
    val format: PcmAudioFormat,
    val encodedByteCount: Long,
) {
    init {
        require(referenceId.isNotBlank() && referenceId.length <= 256)
        require(startedAtElapsedRealtimeMs >= 0)
        require(finishedAtElapsedRealtimeMs >= startedAtElapsedRealtimeMs)
        require(durationMs == finishedAtElapsedRealtimeMs - startedAtElapsedRealtimeMs)
        require(encodedByteCount >= 0)
    }
}

data class VoiceContextTerm(
    val text: String,
    val kind: VoiceContextKind,
    val aliases: Set<String> = emptySet(),
    val boostBps: Int = 0,
    val sensitive: Boolean = false,
) {
    init {
        require(text.isNotBlank() && text.length <= 256)
        require(aliases.size <= 16)
        aliases.forEach { alias ->
            require(alias.isNotBlank() && alias.length <= 256)
        }
        require(boostBps in 0..10_000)
    }
}

data class AsrRequest(
    val requestId: String,
    val sessionId: String,
    val turnIndex: Int,
    val audio: VoiceAudioReference,
    val locale: String,
    val mode: VoiceInputMode,
    val privacyMode: VoicePrivacyMode,
    val contextTerms: List<VoiceContextTerm> = emptyList(),
    val maximumLatencyMs: Long,
    val maximumCloudCalls: Int,
) {
    init {
        require(requestId.isNotBlank() && requestId.length <= 256)
        require(sessionId.isNotBlank() && sessionId.length <= 256)
        require(turnIndex in 0..1_000)
        require(locale.isNotBlank() && locale.length <= 35)
        require(contextTerms.size <= 256)
        require(maximumLatencyMs in 100..120_000)
        require(maximumCloudCalls in 0..4)
        if (privacyMode != VoicePrivacyMode.CLOUD_ASR_ALLOWED) {
            require(maximumCloudCalls == 0) {
                "non-cloud ASR policy cannot reserve cloud calls"
            }
        }
    }
}

data class AsrAlternative(
    val transcript: String,
    val confidenceBps: Int,
) {
    init {
        require(transcript.length <= 100_000)
        require(confidenceBps in 0..10_000)
    }
}

data class AsrSegment(
    val transcript: String,
    val startMs: Long,
    val endMs: Long,
    val confidenceBps: Int,
) {
    init {
        require(transcript.length <= 10_000)
        require(startMs >= 0)
        require(endMs >= startMs)
        require(confidenceBps in 0..10_000)
    }
}

data class AsrAmbiguity(
    val surfaceText: String,
    val alternatives: List<String>,
    val confidenceBps: Int,
    val sensitive: Boolean,
) {
    init {
        require(surfaceText.isNotBlank() && surfaceText.length <= 256)
        require(alternatives.isNotEmpty() && alternatives.size <= 16)
        alternatives.forEach { alternative ->
            require(alternative.isNotBlank() && alternative.length <= 256)
        }
        require(confidenceBps in 0..10_000)
    }
}

data class AsrUsage(
    val engineCalls: Int = 1,
    val cloudCalls: Int = 0,
    val audioDurationMs: Long,
    val estimatedCostMicrousd: Long = 0,
) {
    init {
        require(engineCalls in 0..16)
        require(cloudCalls in 0..16)
        require(audioDurationMs >= 0)
        require(estimatedCostMicrousd >= 0)
    }
}

data class AsrResult(
    val resultId: String,
    val requestId: String,
    val sessionId: String,
    val turnIndex: Int,
    val transcript: String,
    val alternatives: List<AsrAlternative> = emptyList(),
    val segments: List<AsrSegment> = emptyList(),
    val ambiguities: List<AsrAmbiguity> = emptyList(),
    val confidenceBps: Int,
    val locale: String,
    val engineId: String,
    val engineVersion: String,
    val providerId: String? = null,
    val producedAtElapsedRealtimeMs: Long,
    val usage: AsrUsage,
) {
    init {
        require(resultId.isNotBlank() && resultId.length <= 256)
        require(requestId.isNotBlank() && requestId.length <= 256)
        require(sessionId.isNotBlank() && sessionId.length <= 256)
        require(turnIndex in 0..1_000)
        require(transcript.length <= 100_000)
        require(alternatives.size <= 8)
        require(segments.size <= 4_096)
        require(ambiguities.size <= 64)
        require(confidenceBps in 0..10_000)
        require(locale.isNotBlank() && locale.length <= 35)
        require(engineId.isNotBlank() && engineId.length <= 128)
        require(engineVersion.isNotBlank() && engineVersion.length <= 64)
        require(providerId == null || providerId.length <= 128)
        require(producedAtElapsedRealtimeMs >= 0)
    }
}

interface AsrEngine {
    val engineId: String
    val version: String

    suspend fun transcribe(request: AsrRequest): AsrResult

    fun cancel(requestId: String)
}

data class TtsVoiceProfile(
    val profileId: String,
    val locale: String = "fa-IR",
    val preferredVoiceId: String? = null,
    val speechRatePermille: Int = 1_000,
) {
    init {
        require(profileId.isNotBlank() && profileId.length <= 128)
        require(locale.isNotBlank() && locale.length <= 35)
        require(preferredVoiceId == null || preferredVoiceId.length <= 256)
        require(speechRatePermille in 500..2_000)
    }
}

data class TtsRequest(
    val requestId: String,
    val sessionId: String,
    val text: String,
    val profile: TtsVoiceProfile,
    val interruptible: Boolean = true,
) {
    init {
        require(requestId.isNotBlank() && requestId.length <= 256)
        require(sessionId.isNotBlank() && sessionId.length <= 256)
        require(text.isNotBlank() && text.length <= 100_000)
    }
}

interface TtsEngine {
    val engineId: String
    val version: String

    fun speak(request: TtsRequest)

    fun stop(requestId: String)
}

data class VoiceTaskSubmission(
    val requestId: String,
    val sessionId: String,
    val turnIndex: Int,
    val originalTranscript: String,
    val normalizedTranscript: String,
    val locale: String,
    val activationMode: VoiceActivationMode,
    val asrConfidenceBps: Int,
    val receivedAtElapsedRealtimeMs: Long,
) {
    init {
        require(requestId.isNotBlank() && requestId.length <= 256)
        require(sessionId.isNotBlank() && sessionId.length <= 256)
        require(turnIndex in 0..1_000)
        require(originalTranscript.isNotBlank() && originalTranscript.length <= 100_000)
        require(normalizedTranscript.isNotBlank() && normalizedTranscript.length <= 100_000)
        require(locale.isNotBlank() && locale.length <= 35)
        require(asrConfidenceBps in 0..10_000)
        require(receivedAtElapsedRealtimeMs >= 0)
    }
}

interface VoiceTaskSubmitter {
    fun submit(task: VoiceTaskSubmission)

    fun cancel(requestId: String, reason: String)
}

data class VoiceRuntimePolicy(
    val locale: String = "fa-IR",
    val inputMode: VoiceInputMode = VoiceInputMode.COMMAND,
    val privacyMode: VoicePrivacyMode = VoicePrivacyMode.CORE_ALLOWED,
    val asrMinimumConfidenceBps: Int = 7_500,
    val sensitiveEntityMinimumConfidenceBps: Int = 9_000,
    val cancellationMinimumConfidenceBps: Int = 6_000,
    val captureTimeoutMs: Long = 15_000,
    val transcriptionTimeoutMs: Long = 30_000,
    val routingTimeoutMs: Long = 120_000,
    val maximumSessionDurationMs: Long = 180_000,
    val followUpWindowMs: Long = 8_000,
    val maximumCloudAsrCalls: Int = 0,
    val ttsProfile: TtsVoiceProfile = TtsVoiceProfile(profileId = "system-fa-ir"),
) {
    init {
        require(locale.isNotBlank() && locale.length <= 35)
        require(asrMinimumConfidenceBps in 0..10_000)
        require(sensitiveEntityMinimumConfidenceBps in 0..10_000)
        require(cancellationMinimumConfidenceBps in 0..10_000)
        require(captureTimeoutMs in 250..60_000)
        require(transcriptionTimeoutMs in 250..120_000)
        require(routingTimeoutMs in 250..600_000)
        require(maximumSessionDurationMs in 1_000..900_000)
        require(followUpWindowMs in 0..60_000)
        require(maximumCloudAsrCalls in 0..4)
        if (privacyMode != VoicePrivacyMode.CLOUD_ASR_ALLOWED) {
            require(maximumCloudAsrCalls == 0)
        }
    }
}

data class VoiceRuntimeSnapshot(
    val armed: Boolean = false,
    val phase: VoiceSessionPhase = VoiceSessionPhase.DISARMED,
    val configuredActivationMode: VoiceActivationMode? = null,
    val activeActivationMode: VoiceActivationMode? = null,
    val activeSessionId: String? = null,
    val activeActivationId: String? = null,
    val activeAsrRequestId: String? = null,
    val activeTaskRequestId: String? = null,
    val activeTtsRequestId: String? = null,
    val turnIndex: Int = 0,
    val wakePaused: Boolean = true,
    val audioConflict: VoiceAudioConflict? = null,
    val lastEventElapsedRealtimeMs: Long = 0,
    val cooldownUntilElapsedRealtimeMs: Long = 0,
    val sessionStartedAtElapsedRealtimeMs: Long? = null,
    val sessionDeadlineElapsedRealtimeMs: Long? = null,
    val phaseDeadlineElapsedRealtimeMs: Long? = null,
    val followUpUntilElapsedRealtimeMs: Long? = null,
    val normalizedTranscript: String? = null,
    val lastOutcome: VoiceSessionOutcome? = null,
    val lastDetail: String = "",
)

object VoiceIdentity {
    fun sessionId(
        activationMode: VoiceActivationMode,
        profileId: String,
        activationId: String,
    ): String = stableUuid(
        "session:${activationMode.name}:$profileId:$activationId",
    )

    fun asrRequestId(
        sessionId: String,
        turnIndex: Int,
        audioReferenceId: String,
    ): String = stableUuid(
        "asr:$sessionId:$turnIndex:$audioReferenceId",
    )

    fun taskRequestId(
        sessionId: String,
        turnIndex: Int,
        asrResultId: String,
        normalizedTranscript: String,
    ): String = stableUuid(
        "task:$sessionId:$turnIndex:$asrResultId:$normalizedTranscript",
    )

    fun ttsRequestId(
        sessionId: String,
        taskRequestId: String,
        text: String,
    ): String = stableUuid(
        "tts:$sessionId:$taskRequestId:$text",
    )

    private fun stableUuid(value: String): String = UUID.nameUUIDFromBytes(
        "simorgh:voice:$value".toByteArray(StandardCharsets.UTF_8),
    ).toString()
}
