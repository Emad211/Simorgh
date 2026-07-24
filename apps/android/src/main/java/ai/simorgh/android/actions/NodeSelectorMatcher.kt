package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilityNodeSnapshot
import ai.simorgh.android.accessibility.AccessibilitySnapshot
import ai.simorgh.android.accessibility.ScreenBounds
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

@kotlinx.serialization.Serializable
enum class SelectorResolutionOutcome {
    @kotlinx.serialization.SerialName("resolved")
    RESOLVED,

    @kotlinx.serialization.SerialName("not_found")
    NOT_FOUND,

    @kotlinx.serialization.SerialName("ambiguous")
    AMBIGUOUS,

    @kotlinx.serialization.SerialName("invalid_selector")
    INVALID_SELECTOR,
}

enum class SelectorResolutionMode {
    ACTION_TARGET,
    VERIFICATION,
}

data class SelectorCandidateScore(
    val node: AccessibilityNodeSnapshot,
    val score: Int,
    val matchedSignals: List<String>,
)

data class SelectorResolution(
    val outcome: SelectorResolutionOutcome,
    val selected: SelectorCandidateScore? = null,
    val scoreMargin: Int? = null,
    val candidates: List<SelectorCandidateScore> = emptyList(),
    val detail: String = "",
) {
    fun toEvidence(): SelectorResolutionEvidence = SelectorResolutionEvidence(
        outcome = outcome.name.lowercase(),
        selectedNodeId = selected?.node?.nodeId,
        selectedPath = selected?.node?.path,
        selectedScore = selected?.score,
        scoreMargin = scoreMargin,
        candidates = candidates.take(MAX_EVIDENCE_CANDIDATES).map { candidate ->
            SelectorCandidateEvidence(
                nodeId = candidate.node.nodeId,
                path = candidate.node.path,
                score = candidate.score,
                matchedSignals = candidate.matchedSignals,
            )
        },
    )

    private companion object {
        const val MAX_EVIDENCE_CANDIDATES = 5
    }
}

object NodeSelectorMatcher {
    fun resolve(
        snapshot: AccessibilitySnapshot,
        selector: AndroidNodeSelector,
        mode: SelectorResolutionMode = SelectorResolutionMode.ACTION_TARGET,
    ): SelectorResolution {
        val normalizedSelector = runCatching(selector::validated).getOrElse { error ->
            return SelectorResolution(
                outcome = SelectorResolutionOutcome.INVALID_SELECTOR,
                detail = error.message.orEmpty(),
            )
        }

        val candidates = snapshot.nodes.mapNotNull { node ->
            scoreCandidate(snapshot, normalizedSelector, node, mode)
        }.sortedWith(
            compareByDescending<SelectorCandidateScore>(SelectorCandidateScore::score)
                .thenBy { it.node.path }
                .thenBy { it.node.nodeId },
        )

        val best = candidates.firstOrNull()
            ?: return SelectorResolution(
                outcome = SelectorResolutionOutcome.NOT_FOUND,
                candidates = emptyList(),
                detail = "no node satisfied required selector fields and capabilities",
            )

        if (best.score < normalizedSelector.minimumScore) {
            return SelectorResolution(
                outcome = SelectorResolutionOutcome.NOT_FOUND,
                candidates = candidates.take(MAX_CANDIDATES),
                detail = "best candidate score ${best.score} is below " +
                    normalizedSelector.minimumScore,
            )
        }

        val second = candidates.getOrNull(1)
        val margin = if (second == null) best.score else best.score - second.score
        if (second != null && margin < normalizedSelector.minimumMargin) {
            return SelectorResolution(
                outcome = SelectorResolutionOutcome.AMBIGUOUS,
                scoreMargin = margin,
                candidates = candidates.take(MAX_CANDIDATES),
                detail = "top selector margin $margin is below " +
                    normalizedSelector.minimumMargin,
            )
        }

        return SelectorResolution(
            outcome = SelectorResolutionOutcome.RESOLVED,
            selected = best,
            scoreMargin = margin,
            candidates = candidates.take(MAX_CANDIDATES),
        )
    }

    private fun scoreCandidate(
        snapshot: AccessibilitySnapshot,
        selector: AndroidNodeSelector,
        node: AccessibilityNodeSnapshot,
        mode: SelectorResolutionMode,
    ): SelectorCandidateScore? {
        if (!node.visibleToUser) {
            return null
        }
        if (mode == SelectorResolutionMode.ACTION_TARGET && !node.enabled) {
            return null
        }
        val effectivePackage = node.packageName ?: snapshot.activePackage
        if (effectivePackage != selector.packageName) {
            return null
        }
        if (!selector.requiredCapabilities.all { capability -> node.supports(capability) }) {
            return null
        }

        val signals = buildList {
            selector.viewId?.let { expected ->
                add(
                    ScoredSignal(
                        field = SelectorField.VIEW_ID,
                        name = "view_id",
                        matched = node.viewId == expected,
                        score = VIEW_ID_SCORE,
                    ),
                )
            }
            selector.semanticFingerprint?.let { expected ->
                add(
                    ScoredSignal(
                        field = SelectorField.SEMANTIC_FINGERPRINT,
                        name = "semantic_fingerprint",
                        matched = node.semanticFingerprint == expected,
                        score = SEMANTIC_FINGERPRINT_SCORE,
                    ),
                )
            }
            selector.text?.let { expected ->
                add(
                    ScoredSignal(
                        field = SelectorField.TEXT,
                        name = "text_${expected.mode.name.lowercase()}",
                        matched = PersianTextNormalizer.matches(node.text, expected),
                        score = textScore(expected.mode),
                    ),
                )
            }
            selector.contentDescription?.let { expected ->
                add(
                    ScoredSignal(
                        field = SelectorField.CONTENT_DESCRIPTION,
                        name = "content_description_${expected.mode.name.lowercase()}",
                        matched = PersianTextNormalizer.matches(node.contentDescription, expected),
                        score = textScore(expected.mode),
                    ),
                )
            }
            selector.className?.let { expected ->
                add(
                    ScoredSignal(
                        field = SelectorField.CLASS_NAME,
                        name = "class_name",
                        matched = node.className == expected,
                        score = CLASS_SCORE,
                    ),
                )
            }
            selector.path?.let { expected ->
                add(
                    ScoredSignal(
                        field = SelectorField.PATH,
                        name = "path",
                        matched = node.path == expected,
                        score = PATH_SCORE,
                    ),
                )
            }
            selector.bounds?.let { expected ->
                val overlap = intersectionOverUnion(node.bounds, expected)
                add(
                    ScoredSignal(
                        field = SelectorField.BOUNDS,
                        name = "bounds_iou_${(overlap * 100).roundToInt()}",
                        matched = overlap >= REQUIRED_BOUNDS_IOU,
                        score = boundsScore(overlap),
                    ),
                )
            }
        }

        if (
            signals.any { signal ->
                signal.field in selector.requiredFields && !signal.matched
            }
        ) {
            return null
        }

        val matchedSignals = signals.filter(ScoredSignal::matched)
        val score = PACKAGE_SCORE +
            matchedSignals.sumOf(ScoredSignal::score) +
            selector.requiredCapabilities.size * CAPABILITY_SCORE

        return SelectorCandidateScore(
            node = node,
            score = score,
            matchedSignals = buildList {
                add("package_name")
                addAll(matchedSignals.map(ScoredSignal::name))
                addAll(
                    selector.requiredCapabilities
                        .sortedBy(NodeCapability::name)
                        .map { capability ->
                            "capability_${capability.name.lowercase()}"
                        },
                )
            },
        )
    }

    private fun AccessibilityNodeSnapshot.supports(capability: NodeCapability): Boolean =
        when (capability) {
            NodeCapability.CLICKABLE -> clickable
            NodeCapability.LONG_CLICKABLE -> longClickable
            NodeCapability.EDITABLE -> editable
            NodeCapability.SCROLLABLE -> scrollable
            NodeCapability.CHECKABLE -> checkable
            NodeCapability.FOCUSABLE -> focusable
        }

    private fun textScore(mode: TextMatchMode): Int = when (mode) {
        TextMatchMode.EXACT -> EXACT_TEXT_SCORE
        TextMatchMode.CONTAINS -> CONTAINS_TEXT_SCORE
    }

    private fun boundsScore(overlap: Double): Int = when {
        overlap >= 0.999 -> BOUNDS_EXACT_SCORE
        overlap >= 0.75 -> BOUNDS_HIGH_SCORE
        overlap >= 0.50 -> BOUNDS_MEDIUM_SCORE
        else -> 0
    }

    private fun intersectionOverUnion(first: ScreenBounds, second: ScreenBounds): Double {
        val intersectionLeft = max(first.left, second.left)
        val intersectionTop = max(first.top, second.top)
        val intersectionRight = min(first.right, second.right)
        val intersectionBottom = min(first.bottom, second.bottom)
        val intersectionWidth = (intersectionRight - intersectionLeft).coerceAtLeast(0)
        val intersectionHeight = (intersectionBottom - intersectionTop).coerceAtLeast(0)
        val intersection = intersectionWidth.toLong() * intersectionHeight.toLong()
        val firstArea = first.width.toLong() * first.height.toLong()
        val secondArea = second.width.toLong() * second.height.toLong()
        val union = firstArea + secondArea - intersection
        return if (union <= 0) 0.0 else intersection.toDouble() / union.toDouble()
    }

    private data class ScoredSignal(
        val field: SelectorField,
        val name: String,
        val matched: Boolean,
        val score: Int,
    )

    private const val PACKAGE_SCORE = 10
    private const val VIEW_ID_SCORE = 120
    private const val SEMANTIC_FINGERPRINT_SCORE = 100
    private const val EXACT_TEXT_SCORE = 80
    private const val CONTAINS_TEXT_SCORE = 45
    private const val PATH_SCORE = 60
    private const val CLASS_SCORE = 30
    private const val BOUNDS_EXACT_SCORE = 40
    private const val BOUNDS_HIGH_SCORE = 30
    private const val BOUNDS_MEDIUM_SCORE = 20
    private const val CAPABILITY_SCORE = 10
    private const val REQUIRED_BOUNDS_IOU = 0.50
    private const val MAX_CANDIDATES = 5
}
