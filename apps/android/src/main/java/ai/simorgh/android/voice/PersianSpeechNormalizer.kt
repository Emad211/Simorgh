package ai.simorgh.android.voice

import java.text.Normalizer
import java.util.Locale


data class NormalizedPersianSpeech(
    val original: String,
    /** Persian characters and digits normalized while preserving readable punctuation/case. */
    val displayText: String,
    /** Stable task-routing form with punctuation collapsed and Latin text case-folded. */
    val routingText: String,
    val tokens: List<String>,
    val cancellationCommand: Boolean,
)

object PersianSpeechNormalizer {
    private val whitespaceRegex = Regex("\\s+")
    private val routingPunctuationRegex = Regex("[^\\p{L}\\p{N}_./:@+#-]+")
    private val cancellationCommands: Set<String> = setOf(
        "لغو",
        "لغو کن",
        "توقف",
        "توقف کن",
        "بی خیال",
        "بیخیال",
        "ولش کن",
        "قطع کن",
        "کنسل",
        "cancel",
        "stop",
    )

    fun normalize(value: String): NormalizedPersianSpeech {
        val compatibility = Normalizer.normalize(value, Normalizer.Form.NFKC)
        val displayBuilder = StringBuilder(compatibility.length)
        compatibility.forEach { character ->
            val mapped = mapCharacter(character)
            if (mapped == null || shouldDrop(mapped)) {
                return@forEach
            }
            displayBuilder.append(mapped)
        }

        val displayText = whitespaceRegex
            .replace(displayBuilder.toString(), " ")
            .trim()
        val routingText = whitespaceRegex
            .replace(
                routingPunctuationRegex.replace(displayText, " "),
                " ",
            )
            .trim()
            .lowercase(Locale.ROOT)
        val tokens = if (routingText.isEmpty()) {
            emptyList()
        } else {
            routingText.split(' ')
        }
        return NormalizedPersianSpeech(
            original = value,
            displayText = displayText,
            routingText = routingText,
            tokens = tokens,
            cancellationCommand = routingText in cancellationCommands,
        )
    }

    fun isCancellationCommand(value: String): Boolean = normalize(value).cancellationCommand

    private fun mapCharacter(value: Char): Char? = when (value) {
        // Arabic and Persian letter variants.
        '\u064a', '\u0649' -> '\u06cc'
        '\u0643' -> '\u06a9'
        '\u0629', '\u06c0' -> '\u0647'
        '\u0624' -> '\u0648'
        '\u0625', '\u0623', '\u0671' -> '\u0627'
        '\u0640' -> null // Arabic tatweel.

        // Persian digits.
        '\u06f0', '\u0660' -> '0'
        '\u06f1', '\u0661' -> '1'
        '\u06f2', '\u0662' -> '2'
        '\u06f3', '\u0663' -> '3'
        '\u06f4', '\u0664' -> '4'
        '\u06f5', '\u0665' -> '5'
        '\u06f6', '\u0666' -> '6'
        '\u06f7', '\u0667' -> '7'
        '\u06f8', '\u0668' -> '8'
        '\u06f9', '\u0669' -> '9'

        // ASR engines vary in their treatment of Persian half-space. A space is more stable for
        // routing while display text remains readable.
        '\u200c', '\u200d', '\ufeff' -> ' '
        else -> value
    }

    private fun shouldDrop(value: Char): Boolean {
        val type = Character.getType(value)
        return type == Character.NON_SPACING_MARK.toInt() ||
            type == Character.COMBINING_SPACING_MARK.toInt() ||
            type == Character.ENCLOSING_MARK.toInt() ||
            value in '\u0610'..'\u061a' ||
            value in '\u064b'..'\u065f' ||
            value == '\u0670' ||
            value in '\u06d6'..'\u06ed'
    }
}
