package ai.simorgh.android.actions

import java.text.Normalizer
import java.util.Locale

object PersianTextNormalizer {
    private val whitespace = Regex("[\\s\\u200C\\u200D]+")
    private val arabicDiacritics = Regex("[\\u064B-\\u065F\\u0670\\u06D6-\\u06ED]")

    fun normalize(value: String, caseSensitive: Boolean = false): String {
        var normalized = Normalizer.normalize(value, Normalizer.Form.NFKC)
            .replace('\u064A', '\u06CC')
            .replace('\u0649', '\u06CC')
            .replace('\u0643', '\u06A9')
            .replace("\u0640", "")
            .replace(arabicDiacritics, "")
            .map(::normalizeDigit)
            .joinToString(separator = "")
            .replace(whitespace, " ")
            .trim()

        if (!caseSensitive) {
            normalized = normalized.lowercase(Locale.ROOT)
        }
        return normalized
    }

    fun matches(actual: String?, criterion: TextCriterion): Boolean {
        if (actual == null) {
            return false
        }
        val normalizedActual = normalize(actual, criterion.caseSensitive)
        val normalizedExpected = normalize(criterion.value, criterion.caseSensitive)
        return when (criterion.mode) {
            TextMatchMode.EXACT -> normalizedActual == normalizedExpected
            TextMatchMode.CONTAINS -> normalizedActual.contains(normalizedExpected)
        }
    }

    private fun normalizeDigit(character: Char): Char = when (character) {
        in '\u06F0'..'\u06F9' -> '0' + (character.code - '\u06F0'.code)
        in '\u0660'..'\u0669' -> '0' + (character.code - '\u0660'.code)
        else -> character
    }
}
