package ai.simorgh.android.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PersianSpeechNormalizerTest {
    @Test
    fun `Arabic keyboard variants normalize to Persian letters`() {
        val normalized = PersianSpeechNormalizer.normalize(
            "گيت هاب و كدنويسي براي پروژه",
        )

        assertEquals("گیت هاب و کدنویسی برای پروژه", normalized.displayText)
        assertEquals("گیت هاب و کدنویسی برای پروژه", normalized.routingText)
    }

    @Test
    fun `mixed Persian and English technical names remain readable`() {
        val normalized = PersianSpeechNormalizer.normalize(
            "GitHub PR شماره ۱۲۳ برای com.Example.App و API v2",
        )

        assertEquals(
            "GitHub PR شماره 123 برای com.Example.App و API v2",
            normalized.displayText,
        )
        assertEquals(
            "github pr شماره 123 برای com.example.app و api v2",
            normalized.routingText,
        )
        assertTrue("com.example.app" in normalized.tokens)
        assertTrue("api" in normalized.tokens)
    }

    @Test
    fun `Arabic and Persian digits share one routing identity`() {
        val persian = PersianSpeechNormalizer.normalize("نسخه ۱۲۳")
        val arabic = PersianSpeechNormalizer.normalize("نسخه ١٢٣")
        val ascii = PersianSpeechNormalizer.normalize("نسخه 123")

        assertEquals(ascii.routingText, persian.routingText)
        assertEquals(ascii.routingText, arabic.routingText)
    }

    @Test
    fun `half spaces tatweel and Arabic diacritics do not fragment routing`() {
        val normalized = PersianSpeechNormalizer.normalize(
            "می\u200cخواهم  سِــیمرغ   برنامه\u200dنویسی کند",
        )

        assertEquals("می خواهم سیمرغ برنامه نویسی کند", normalized.routingText)
    }

    @Test
    fun `cancellation requires an explicit cancellation command`() {
        assertTrue(PersianSpeechNormalizer.isCancellationCommand("بیخیال"))
        assertTrue(PersianSpeechNormalizer.isCancellationCommand("لغو کن"))
        assertTrue(PersianSpeechNormalizer.isCancellationCommand("STOP"))

        assertFalse(PersianSpeechNormalizer.isCancellationCommand("لغو قرارداد را بررسی کن"))
        assertFalse(PersianSpeechNormalizer.isCancellationCommand("درباره توقف سرویس تحقیق کن"))
    }

    @Test
    fun `stable voice identities replay exact callbacks and separate changed content`() {
        val sessionOne = VoiceIdentity.sessionId(
            VoiceActivationMode.FOREGROUND_WAKE,
            profileId = "simorgh-fa",
            activationId = "detection-1",
        )
        val sessionReplay = VoiceIdentity.sessionId(
            VoiceActivationMode.FOREGROUND_WAKE,
            profileId = "simorgh-fa",
            activationId = "detection-1",
        )
        val sessionTwo = VoiceIdentity.sessionId(
            VoiceActivationMode.FOREGROUND_WAKE,
            profileId = "simorgh-fa",
            activationId = "detection-2",
        )

        assertEquals(sessionOne, sessionReplay)
        assertNotEquals(sessionOne, sessionTwo)

        val taskOne = VoiceIdentity.taskRequestId(
            sessionId = sessionOne,
            turnIndex = 0,
            asrResultId = "result-1",
            normalizedTranscript = "گیت هاب را بررسی کن",
        )
        val taskReplay = VoiceIdentity.taskRequestId(
            sessionId = sessionOne,
            turnIndex = 0,
            asrResultId = "result-1",
            normalizedTranscript = "گیت هاب را بررسی کن",
        )
        val changedTask = VoiceIdentity.taskRequestId(
            sessionId = sessionOne,
            turnIndex = 0,
            asrResultId = "result-1",
            normalizedTranscript = "تقویم را بررسی کن",
        )

        assertEquals(taskOne, taskReplay)
        assertNotEquals(taskOne, changedTask)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `local only ASR policy cannot reserve a cloud call`() {
        AsrRequest(
            requestId = "request",
            sessionId = "session",
            turnIndex = 0,
            audio = audioReference(),
            locale = "fa-IR",
            mode = VoiceInputMode.COMMAND,
            privacyMode = VoicePrivacyMode.LOCAL_ONLY,
            maximumLatencyMs = 1_000,
            maximumCloudCalls = 1,
        )
    }

    private fun audioReference(): VoiceAudioReference = VoiceAudioReference(
        referenceId = "audio",
        startedAtElapsedRealtimeMs = 100,
        finishedAtElapsedRealtimeMs = 500,
        durationMs = 400,
        format = PcmAudioFormat(sampleRateHz = 16_000),
        encodedByteCount = 12_800,
    )
}
