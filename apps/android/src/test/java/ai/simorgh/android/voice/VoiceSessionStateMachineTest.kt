package ai.simorgh.android.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceSessionStateMachineTest {
    @Test
    fun `no ASR task or provider effect exists before wake or push to talk`() {
        val machine = machine()

        val tick = machine.dispatch(VoiceEvent.Tick(elapsedRealtimeMs = 10))
        val armed = machine.dispatch(
            VoiceEvent.Arm(
                activationMode = VoiceActivationMode.FOREGROUND_WAKE,
                elapsedRealtimeMs = 20,
            )
        )
        val weakWake = machine.dispatch(
            VoiceEvent.WakeDetected(
                detection(
                    id = "weak",
                    atMs = 30,
                    confidenceBps = 6_000,
                )
            )
        )

        assertTrue(tick.effects.isEmpty())
        assertEquals(
            listOf(VoiceEffect.ResumeWakeEngine("voice runtime armed")),
            armed.effects,
        )
        assertFalse(weakWake.accepted)
        assertNoExternalEffects(tick, armed, weakWake)
        assertEquals(VoiceSessionPhase.ARMED, machine.snapshot().phase)
    }

    @Test
    fun `valid local wake opens one capture and duplicate callback is ignored`() {
        val machine = armedMachine()

        val accepted = machine.dispatch(
            VoiceEvent.WakeDetected(detection(id = "wake-1", atMs = 200))
        )
        val duplicate = machine.dispatch(
            VoiceEvent.WakeDetected(detection(id = "wake-1", atMs = 200))
        )

        assertTrue(accepted.accepted)
        assertEquals(VoiceSessionPhase.CAPTURING, accepted.current.phase)
        assertEquals(1, accepted.effects.filterIsInstance<VoiceEffect.StartCapture>().size)
        assertEquals(1, accepted.effects.filterIsInstance<VoiceEffect.PauseWakeEngine>().size)
        assertFalse(duplicate.accepted)
        assertTrue(duplicate.reason.contains("duplicate"))
        assertTrue(duplicate.effects.isEmpty())
        assertEquals(accepted.current.activeSessionId, duplicate.current.activeSessionId)
    }

    @Test
    fun `cooldown suppresses a second utterance after cancellation`() {
        val machine = armedMachine()
        machine.dispatch(VoiceEvent.WakeDetected(detection(id = "wake-1", atMs = 200)))
        machine.dispatch(VoiceEvent.Cancel(reason = "fixture", elapsedRealtimeMs = 250))

        val insideCooldown = machine.dispatch(
            VoiceEvent.WakeDetected(detection(id = "wake-2", atMs = 1_000))
        )
        val afterCooldown = machine.dispatch(
            VoiceEvent.WakeDetected(detection(id = "wake-3", atMs = 2_800))
        )

        assertFalse(insideCooldown.accepted)
        assertTrue(insideCooldown.reason.contains("cooldown"))
        assertTrue(afterCooldown.accepted)
        assertEquals(VoiceSessionPhase.CAPTURING, afterCooldown.current.phase)
    }

    @Test
    fun `audio conflict pauses armed wake and blocks detections until cleared`() {
        val machine = armedMachine()

        val conflict = machine.dispatch(
            VoiceEvent.AudioConflictChanged(
                conflict = VoiceAudioConflict.PHONE_CALL,
                elapsedRealtimeMs = 150,
            )
        )
        val wake = machine.dispatch(
            VoiceEvent.WakeDetected(detection(id = "during-call", atMs = 200))
        )
        val cleared = machine.dispatch(
            VoiceEvent.AudioConflictChanged(
                conflict = null,
                elapsedRealtimeMs = 250,
            )
        )

        assertEquals(
            1,
            conflict.effects.filterIsInstance<VoiceEffect.PauseWakeEngine>().size,
        )
        assertFalse(wake.accepted)
        assertTrue(wake.effects.isEmpty())
        assertEquals(1, cleared.effects.filterIsInstance<VoiceEffect.ResumeWakeEngine>().size)
        assertFalse(cleared.current.wakePaused)
    }

    @Test
    fun `push to talk can start from disarmed state without pretending wake permission`() {
        val machine = machine()

        val transition = machine.dispatch(
            VoiceEvent.PushToTalkStarted(
                activationId = "button-press-1",
                inputMode = VoiceInputMode.DICTATION,
                elapsedRealtimeMs = 100,
            )
        )

        assertTrue(transition.accepted)
        assertFalse(transition.current.armed)
        assertEquals(VoiceActivationMode.PUSH_TO_TALK, transition.current.activeActivationMode)
        assertEquals(VoiceSessionPhase.CAPTURING, transition.current.phase)
        assertEquals(1, transition.effects.filterIsInstance<VoiceEffect.StartCapture>().size)
        assertTrue(transition.effects.filterIsInstance<VoiceEffect.PauseWakeEngine>().isEmpty())
    }

    @Test
    fun `capture after wake is the first point that may request ASR`() {
        val fixture = activatedFixture()

        val captured = fixture.machine.dispatch(
            VoiceEvent.CaptureCompleted(
                sessionId = fixture.sessionId,
                audio = audio(startMs = 220, endMs = 700),
                contextTerms = listOf(
                    VoiceContextTerm(
                        text = "Emad211/Simorgh",
                        kind = VoiceContextKind.REPOSITORY,
                        aliases = setOf("Simorgh"),
                        boostBps = 8_000,
                    )
                ),
                elapsedRealtimeMs = 700,
            )
        )

        assertTrue(captured.accepted)
        assertEquals(VoiceSessionPhase.TRANSCRIBING, captured.current.phase)
        val request = captured.effects
            .filterIsInstance<VoiceEffect.RequestTranscription>()
            .single()
            .request
        assertEquals(fixture.sessionId, request.sessionId)
        assertEquals(VoicePrivacyMode.CORE_ALLOWED, request.privacyMode)
        assertEquals(0, request.maximumCloudCalls)
        assertEquals("Emad211/Simorgh", request.contextTerms.single().text)
        assertTrue(captured.effects.filterIsInstance<VoiceEffect.SubmitTask>().isEmpty())
    }

    @Test
    fun `high confidence Persian transcript creates one stable specialist task`() {
        val fixture = transcriptionFixture()
        val result = asrResult(
            request = fixture.request,
            transcript = "ریپازیتوری GitHub شماره ۱۲۳ را بررسی کن",
            confidenceBps = 9_000,
            atMs = 800,
        )

        val accepted = fixture.machine.dispatch(
            VoiceEvent.AsrCompleted(
                sessionId = fixture.sessionId,
                result = result,
                elapsedRealtimeMs = 800,
            )
        )
        val duplicate = fixture.machine.dispatch(
            VoiceEvent.AsrCompleted(
                sessionId = fixture.sessionId,
                result = result,
                elapsedRealtimeMs = 800,
            )
        )

        assertTrue(accepted.accepted)
        assertEquals(VoiceSessionPhase.ROUTING, accepted.current.phase)
        val task = accepted.effects.filterIsInstance<VoiceEffect.SubmitTask>().single().task
        assertEquals(
            "ریپازیتوری github شماره 123 را بررسی کن",
            task.normalizedTranscript,
        )
        assertEquals(
            VoiceIdentity.taskRequestId(
                sessionId = fixture.sessionId,
                turnIndex = 0,
                asrResultId = result.resultId,
                normalizedTranscript = task.normalizedTranscript,
            ),
            task.requestId,
        )
        assertFalse(duplicate.accepted)
        assertTrue(duplicate.effects.filterIsInstance<VoiceEffect.SubmitTask>().isEmpty())
    }

    @Test
    fun `low confidence transcript asks for clarification and never submits task`() {
        val fixture = transcriptionFixture()

        val transition = fixture.machine.dispatch(
            VoiceEvent.AsrCompleted(
                sessionId = fixture.sessionId,
                result = asrResult(
                    request = fixture.request,
                    transcript = "گیت هاب شاید",
                    confidenceBps = 5_000,
                    atMs = 800,
                ),
                elapsedRealtimeMs = 800,
            )
        )

        assertTrue(transition.accepted)
        assertEquals(VoiceSessionPhase.SPEAKING, transition.current.phase)
        assertEquals(
            VoiceClarificationReason.LOW_CONFIDENCE,
            transition.effects
                .filterIsInstance<VoiceEffect.RequestClarification>()
                .single()
                .reason,
        )
        assertEquals(1, transition.effects.filterIsInstance<VoiceEffect.Speak>().size)
        assertTrue(transition.effects.filterIsInstance<VoiceEffect.SubmitTask>().isEmpty())

        val tts = transition.effects.filterIsInstance<VoiceEffect.Speak>().single().request
        val retry = fixture.machine.dispatch(
            VoiceEvent.SpeechFinished(
                sessionId = fixture.sessionId,
                requestId = tts.requestId,
                elapsedRealtimeMs = 900,
            )
        )
        assertEquals(VoiceSessionPhase.CAPTURING, retry.current.phase)
        assertEquals(1, retry.effects.filterIsInstance<VoiceEffect.StartCapture>().size)
        assertEquals(0, retry.current.turnIndex)
    }

    @Test
    fun `sensitive ambiguous entity always requires confirmation below strict threshold`() {
        val fixture = transcriptionFixture()

        val transition = fixture.machine.dispatch(
            VoiceEvent.AsrCompleted(
                sessionId = fixture.sessionId,
                result = asrResult(
                    request = fixture.request,
                    transcript = "به علی پیام فروش را بفرست",
                    confidenceBps = 9_500,
                    atMs = 800,
                    ambiguities = listOf(
                        AsrAmbiguity(
                            surfaceText = "علی",
                            alternatives = listOf("علی احمدی", "علی اکبری"),
                            confidenceBps = 8_000,
                            sensitive = true,
                        )
                    ),
                ),
                elapsedRealtimeMs = 800,
            )
        )

        assertEquals(VoiceSessionPhase.SPEAKING, transition.current.phase)
        assertEquals(
            VoiceClarificationReason.SENSITIVE_ENTITY,
            transition.effects
                .filterIsInstance<VoiceEffect.RequestClarification>()
                .single()
                .reason,
        )
        assertTrue(transition.effects.filterIsInstance<VoiceEffect.SubmitTask>().isEmpty())
    }

    @Test
    fun `spoken cancellation terminates session and resumes wake without task`() {
        val fixture = transcriptionFixture()

        val transition = fixture.machine.dispatch(
            VoiceEvent.AsrCompleted(
                sessionId = fixture.sessionId,
                result = asrResult(
                    request = fixture.request,
                    transcript = "بیخیال",
                    confidenceBps = 9_000,
                    atMs = 800,
                ),
                elapsedRealtimeMs = 800,
            )
        )

        assertTrue(transition.accepted)
        assertEquals(VoiceSessionOutcome.CANCELLED, transition.current.lastOutcome)
        assertEquals(VoiceSessionPhase.ARMED, transition.current.phase)
        assertNull(transition.current.activeSessionId)
        assertTrue(transition.effects.filterIsInstance<VoiceEffect.SubmitTask>().isEmpty())
        assertEquals(1, transition.effects.filterIsInstance<VoiceEffect.ResumeWakeEngine>().size)
    }

    @Test
    fun `explicit cancellation after task acceptance cancels exact task identity`() {
        val fixture = routedFixture()
        fixture.machine.dispatch(
            VoiceEvent.TaskAccepted(
                sessionId = fixture.sessionId,
                requestId = fixture.taskRequestId,
                elapsedRealtimeMs = 900,
            )
        )

        val cancelled = fixture.machine.dispatch(
            VoiceEvent.Cancel(
                reason = "کاربر گفت توقف",
                elapsedRealtimeMs = 1_000,
            )
        )

        assertEquals(VoiceSessionOutcome.CANCELLED, cancelled.current.lastOutcome)
        val taskCancellation = cancelled.effects
            .filterIsInstance<VoiceEffect.CancelTask>()
            .single()
        assertEquals(fixture.taskRequestId, taskCancellation.requestId)
        assertEquals(VoiceSessionPhase.ARMED, cancelled.current.phase)
    }

    @Test
    fun `new wake cannot interrupt TTS and barge in uses an explicit follow up turn`() {
        val fixture = speakingFixture(allowFollowUp = true)

        val wakeDuringTts = fixture.machine.dispatch(
            VoiceEvent.WakeDetected(detection(id = "during-tts", atMs = 1_100))
        )
        val bargeIn = fixture.machine.dispatch(
            VoiceEvent.BargeIn(
                activationId = "barge-1",
                elapsedRealtimeMs = 1_200,
            )
        )

        assertFalse(wakeDuringTts.accepted)
        assertTrue(wakeDuringTts.effects.isEmpty())
        assertTrue(bargeIn.accepted)
        assertEquals(VoiceSessionPhase.FOLLOW_UP, bargeIn.current.phase)
        assertEquals(1, bargeIn.current.turnIndex)
        assertEquals(1, bargeIn.effects.filterIsInstance<VoiceEffect.StopSpeaking>().size)
        assertEquals(1, bargeIn.effects.filterIsInstance<VoiceEffect.StartCapture>().size)
    }

    @Test
    fun `completed TTS may start one bounded follow up capture`() {
        val fixture = speakingFixture(allowFollowUp = true)

        val finished = fixture.machine.dispatch(
            VoiceEvent.SpeechFinished(
                sessionId = fixture.sessionId,
                requestId = fixture.ttsRequestId,
                elapsedRealtimeMs = 1_200,
            )
        )

        assertEquals(VoiceSessionPhase.FOLLOW_UP, finished.current.phase)
        assertEquals(1, finished.current.turnIndex)
        assertNotNull(finished.current.followUpUntilElapsedRealtimeMs)
        val capture = finished.effects.filterIsInstance<VoiceEffect.StartCapture>().single()
        assertEquals(VoiceActivationMode.FOLLOW_UP, capture.activationMode)
        assertEquals(VoiceInputMode.CONVERSATION, capture.inputMode)
    }

    @Test
    fun `completed TTS without follow up closes session and resumes wake`() {
        val fixture = speakingFixture(allowFollowUp = false)

        val finished = fixture.machine.dispatch(
            VoiceEvent.SpeechFinished(
                sessionId = fixture.sessionId,
                requestId = fixture.ttsRequestId,
                elapsedRealtimeMs = 1_200,
            )
        )

        assertEquals(VoiceSessionOutcome.SUCCEEDED, finished.current.lastOutcome)
        assertEquals(VoiceSessionPhase.ARMED, finished.current.phase)
        assertNull(finished.current.activeSessionId)
        assertEquals(1, finished.effects.filterIsInstance<VoiceEffect.ResumeWakeEngine>().size)
    }

    @Test
    fun `capture deadline expires using monotonic time and stops local capture`() {
        val fixture = activatedFixture()
        val deadline = requireNotNull(
            fixture.machine.snapshot().phaseDeadlineElapsedRealtimeMs,
        )

        val expired = fixture.machine.dispatch(
            VoiceEvent.Tick(elapsedRealtimeMs = deadline)
        )

        assertEquals(VoiceSessionOutcome.TIMED_OUT, expired.current.lastOutcome)
        assertEquals(VoiceSessionPhase.ARMED, expired.current.phase)
        assertEquals(1, expired.effects.filterIsInstance<VoiceEffect.StopCapture>().size)
        assertEquals(1, expired.effects.filterIsInstance<VoiceEffect.ResumeWakeEngine>().size)
    }

    @Test
    fun `backwards monotonic event is rejected without changing active state`() {
        val fixture = activatedFixture()
        val before = fixture.machine.snapshot()

        val stale = fixture.machine.dispatch(
            VoiceEvent.Tick(elapsedRealtimeMs = 150)
        )

        assertFalse(stale.accepted)
        assertTrue(stale.reason.contains("backwards"))
        assertEquals(before, fixture.machine.snapshot())
    }

    @Test
    fun `audio conflict during capture stops session and keeps wake paused`() {
        val fixture = activatedFixture()

        val interrupted = fixture.machine.dispatch(
            VoiceEvent.AudioConflictChanged(
                conflict = VoiceAudioConflict.OTHER_RECORDING,
                elapsedRealtimeMs = 300,
            )
        )

        assertEquals(VoiceSessionOutcome.BLOCKED, interrupted.current.lastOutcome)
        assertEquals(VoiceSessionPhase.ARMED, interrupted.current.phase)
        assertEquals(VoiceAudioConflict.OTHER_RECORDING, interrupted.current.audioConflict)
        assertTrue(interrupted.current.wakePaused)
        assertEquals(1, interrupted.effects.filterIsInstance<VoiceEffect.StopCapture>().size)
        assertTrue(interrupted.effects.filterIsInstance<VoiceEffect.ResumeWakeEngine>().isEmpty())
    }

    @Test
    fun `future ASR timestamp fails closed`() {
        val fixture = transcriptionFixture()

        val blocked = fixture.machine.dispatch(
            VoiceEvent.AsrCompleted(
                sessionId = fixture.sessionId,
                result = asrResult(
                    request = fixture.request,
                    transcript = "گیت هاب را بررسی کن",
                    confidenceBps = 9_000,
                    atMs = 900,
                ).copy(producedAtElapsedRealtimeMs = 901),
                elapsedRealtimeMs = 900,
            )
        )

        assertEquals(VoiceSessionOutcome.BLOCKED, blocked.current.lastOutcome)
        assertEquals(VoiceSessionPhase.ARMED, blocked.current.phase)
        assertTrue(blocked.effects.filterIsInstance<VoiceEffect.SubmitTask>().isEmpty())
    }

    private fun machine(
        policy: VoiceRuntimePolicy = VoiceRuntimePolicy(),
    ): VoiceSessionStateMachine = VoiceSessionStateMachine(
        wakeProfile = WakePhraseProfile(
            profileId = "simorgh-fa",
            phrases = setOf("سیمرغ"),
            minimumConfidenceBps = 7_500,
            cooldownMs = 2_500,
        ),
        policy = policy,
    )

    private fun armedMachine(): VoiceSessionStateMachine = machine().also { value ->
        value.dispatch(
            VoiceEvent.Arm(
                activationMode = VoiceActivationMode.FOREGROUND_WAKE,
                elapsedRealtimeMs = 100,
            )
        )
    }

    private fun activatedFixture(): ActivatedFixture {
        val machine = armedMachine()
        val transition = machine.dispatch(
            VoiceEvent.WakeDetected(detection(id = "wake-1", atMs = 200))
        )
        return ActivatedFixture(
            machine = machine,
            sessionId = requireNotNull(transition.current.activeSessionId),
        )
    }

    private fun transcriptionFixture(): TranscriptionFixture {
        val activated = activatedFixture()
        val transition = activated.machine.dispatch(
            VoiceEvent.CaptureCompleted(
                sessionId = activated.sessionId,
                audio = audio(startMs = 220, endMs = 700),
                elapsedRealtimeMs = 700,
            )
        )
        val request = transition.effects
            .filterIsInstance<VoiceEffect.RequestTranscription>()
            .single()
            .request
        return TranscriptionFixture(
            machine = activated.machine,
            sessionId = activated.sessionId,
            request = request,
        )
    }

    private fun routedFixture(): RoutedFixture {
        val transcribing = transcriptionFixture()
        val transition = transcribing.machine.dispatch(
            VoiceEvent.AsrCompleted(
                sessionId = transcribing.sessionId,
                result = asrResult(
                    request = transcribing.request,
                    transcript = "گیت هاب را بررسی کن",
                    confidenceBps = 9_000,
                    atMs = 800,
                ),
                elapsedRealtimeMs = 800,
            )
        )
        val task = transition.effects.filterIsInstance<VoiceEffect.SubmitTask>().single().task
        return RoutedFixture(
            machine = transcribing.machine,
            sessionId = transcribing.sessionId,
            taskRequestId = task.requestId,
        )
    }

    private fun speakingFixture(allowFollowUp: Boolean): SpeakingFixture {
        val routed = routedFixture()
        routed.machine.dispatch(
            VoiceEvent.TaskAccepted(
                sessionId = routed.sessionId,
                requestId = routed.taskRequestId,
                elapsedRealtimeMs = 900,
            )
        )
        val transition = routed.machine.dispatch(
            VoiceEvent.TaskResultReady(
                sessionId = routed.sessionId,
                requestId = routed.taskRequestId,
                responseText = "ریپازیتوری بررسی شد و سه مورد مهم پیدا شد.",
                allowFollowUp = allowFollowUp,
                elapsedRealtimeMs = 1_000,
            )
        )
        val tts = transition.effects.filterIsInstance<VoiceEffect.Speak>().single().request
        return SpeakingFixture(
            machine = routed.machine,
            sessionId = routed.sessionId,
            ttsRequestId = tts.requestId,
        )
    }

    private fun detection(
        id: String,
        atMs: Long,
        confidenceBps: Int = 9_000,
    ): WakeDetection = WakeDetection(
        detectionId = id,
        profileId = "simorgh-fa",
        phrase = "سیمرغ",
        confidenceBps = confidenceBps,
        capturedAtElapsedRealtimeMs = atMs,
        engineId = "fake-local-wake",
        engineVersion = "1.0",
    )

    private fun audio(startMs: Long, endMs: Long): VoiceAudioReference =
        VoiceAudioReference(
            referenceId = "audio-$startMs-$endMs",
            startedAtElapsedRealtimeMs = startMs,
            finishedAtElapsedRealtimeMs = endMs,
            durationMs = endMs - startMs,
            format = PcmAudioFormat(sampleRateHz = 16_000),
            encodedByteCount = (endMs - startMs) * 32,
        )

    private fun asrResult(
        request: AsrRequest,
        transcript: String,
        confidenceBps: Int,
        atMs: Long,
        ambiguities: List<AsrAmbiguity> = emptyList(),
    ): AsrResult = AsrResult(
        resultId = "result-${request.turnIndex}-$atMs",
        requestId = request.requestId,
        sessionId = request.sessionId,
        turnIndex = request.turnIndex,
        transcript = transcript,
        confidenceBps = confidenceBps,
        locale = "fa-IR",
        engineId = "fake-persian-asr",
        engineVersion = "1.0",
        producedAtElapsedRealtimeMs = atMs,
        usage = AsrUsage(
            engineCalls = 1,
            cloudCalls = 0,
            audioDurationMs = request.audio.durationMs,
        ),
        ambiguities = ambiguities,
    )

    private fun assertNoExternalEffects(vararg transitions: VoiceTransition) {
        transitions.forEach { transition ->
            assertTrue(
                transition.effects.none { effect ->
                    effect is VoiceEffect.RequestTranscription ||
                        effect is VoiceEffect.SubmitTask ||
                        effect is VoiceEffect.Speak
                }
            )
        }
    }

    private data class ActivatedFixture(
        val machine: VoiceSessionStateMachine,
        val sessionId: String,
    )

    private data class TranscriptionFixture(
        val machine: VoiceSessionStateMachine,
        val sessionId: String,
        val request: AsrRequest,
    )

    private data class RoutedFixture(
        val machine: VoiceSessionStateMachine,
        val sessionId: String,
        val taskRequestId: String,
    )

    private data class SpeakingFixture(
        val machine: VoiceSessionStateMachine,
        val sessionId: String,
        val ttsRequestId: String,
    )
}
