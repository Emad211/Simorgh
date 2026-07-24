package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.AccessibilitySnapshot

data class PredicateEvaluation(
    val outcome: PredicateOutcome,
    val detail: String,
    val resolution: SelectorResolution? = null,
) {
    fun toEvidence(predicate: UiPredicate): PredicateEvidence = PredicateEvidence(
        kind = predicateKind(predicate),
        outcome = outcome,
        detail = detail,
        resolution = resolution?.toEvidence(),
    )

    private fun predicateKind(predicate: UiPredicate): String = when (predicate) {
        is ActivePackageEqualsPredicate -> "active_package_equals"
        is NodeExistsPredicate -> "node_exists"
        is NodeAbsentPredicate -> "node_absent"
        is NodeTextEqualsPredicate -> "node_text_equals"
        is NodeCheckedEqualsPredicate -> "node_checked_equals"
        is NodeEnabledEqualsPredicate -> "node_enabled_equals"
    }
}

data class VerificationEvaluation(
    val outcome: PredicateOutcome,
    val predicates: List<Pair<UiPredicate, PredicateEvaluation>>,
) {
    val evidence: List<PredicateEvidence>
        get() = predicates.map { (predicate, evaluation) -> evaluation.toEvidence(predicate) }
}

object UiPostconditionEvaluator {
    fun evaluate(
        snapshot: AccessibilitySnapshot,
        policy: AndroidVerificationPolicy,
    ): VerificationEvaluation {
        val results = policy.predicates.map { predicate ->
            predicate to evaluatePredicate(snapshot, predicate)
        }
        val outcome = when {
            results.any { (_, result) -> result.outcome == PredicateOutcome.INDETERMINATE } ->
                PredicateOutcome.INDETERMINATE
            results.all { (_, result) -> result.outcome == PredicateOutcome.SATISFIED } ->
                PredicateOutcome.SATISFIED
            else -> PredicateOutcome.UNSATISFIED
        }
        return VerificationEvaluation(outcome = outcome, predicates = results)
    }

    fun evaluatePredicate(
        snapshot: AccessibilitySnapshot,
        predicate: UiPredicate,
    ): PredicateEvaluation = when (predicate) {
        is ActivePackageEqualsPredicate -> {
            val satisfied = snapshot.activePackage == predicate.packageName
            PredicateEvaluation(
                outcome = if (satisfied) {
                    PredicateOutcome.SATISFIED
                } else {
                    PredicateOutcome.UNSATISFIED
                },
                detail = "active package=${snapshot.activePackage.orEmpty()} " +
                    "expected=${predicate.packageName}",
            )
        }

        is NodeExistsPredicate -> evaluateExists(snapshot, predicate.selector, shouldExist = true)
        is NodeAbsentPredicate -> evaluateExists(snapshot, predicate.selector, shouldExist = false)
        is NodeTextEqualsPredicate -> evaluateNodeText(snapshot, predicate)
        is NodeCheckedEqualsPredicate -> evaluateNodeChecked(snapshot, predicate)
        is NodeEnabledEqualsPredicate -> evaluateNodeEnabled(snapshot, predicate)
    }

    private fun evaluateExists(
        snapshot: AccessibilitySnapshot,
        selector: AndroidNodeSelector,
        shouldExist: Boolean,
    ): PredicateEvaluation {
        val resolution = NodeSelectorMatcher.resolve(snapshot, selector)
        return when (resolution.outcome) {
            SelectorResolutionOutcome.RESOLVED -> PredicateEvaluation(
                outcome = if (shouldExist) {
                    PredicateOutcome.SATISFIED
                } else {
                    PredicateOutcome.UNSATISFIED
                },
                detail = if (shouldExist) "target node exists" else "target node still exists",
                resolution = resolution,
            )

            SelectorResolutionOutcome.NOT_FOUND -> PredicateEvaluation(
                outcome = if (shouldExist) {
                    PredicateOutcome.UNSATISFIED
                } else {
                    PredicateOutcome.SATISFIED
                },
                detail = if (shouldExist) "target node was not found" else "target node is absent",
                resolution = resolution,
            )

            SelectorResolutionOutcome.AMBIGUOUS,
            SelectorResolutionOutcome.INVALID_SELECTOR,
            -> PredicateEvaluation(
                outcome = PredicateOutcome.INDETERMINATE,
                detail = resolution.detail,
                resolution = resolution,
            )
        }
    }

    private fun evaluateNodeText(
        snapshot: AccessibilitySnapshot,
        predicate: NodeTextEqualsPredicate,
    ): PredicateEvaluation {
        val resolution = NodeSelectorMatcher.resolve(snapshot, predicate.selector)
        val selected = resolution.selected?.node
        if (resolution.outcome != SelectorResolutionOutcome.RESOLVED || selected == null) {
            return unresolvedPredicate(resolution)
        }
        val actual = PersianTextNormalizer.normalize(selected.text.orEmpty(), predicate.caseSensitive)
        val expected = PersianTextNormalizer.normalize(predicate.expectedText, predicate.caseSensitive)
        return PredicateEvaluation(
            outcome = if (actual == expected) {
                PredicateOutcome.SATISFIED
            } else {
                PredicateOutcome.UNSATISFIED
            },
            detail = "resolved node text comparison: actual=$actual expected=$expected",
            resolution = resolution,
        )
    }

    private fun evaluateNodeChecked(
        snapshot: AccessibilitySnapshot,
        predicate: NodeCheckedEqualsPredicate,
    ): PredicateEvaluation {
        val resolution = NodeSelectorMatcher.resolve(snapshot, predicate.selector)
        val selected = resolution.selected?.node
        if (resolution.outcome != SelectorResolutionOutcome.RESOLVED || selected == null) {
            return unresolvedPredicate(resolution)
        }
        return PredicateEvaluation(
            outcome = if (selected.checked == predicate.expectedChecked) {
                PredicateOutcome.SATISFIED
            } else {
                PredicateOutcome.UNSATISFIED
            },
            detail = "resolved node checked=${selected.checked} " +
                "expected=${predicate.expectedChecked}",
            resolution = resolution,
        )
    }

    private fun evaluateNodeEnabled(
        snapshot: AccessibilitySnapshot,
        predicate: NodeEnabledEqualsPredicate,
    ): PredicateEvaluation {
        val resolution = NodeSelectorMatcher.resolve(snapshot, predicate.selector)
        val selected = resolution.selected?.node
        if (resolution.outcome != SelectorResolutionOutcome.RESOLVED || selected == null) {
            return unresolvedPredicate(resolution)
        }
        return PredicateEvaluation(
            outcome = if (selected.enabled == predicate.expectedEnabled) {
                PredicateOutcome.SATISFIED
            } else {
                PredicateOutcome.UNSATISFIED
            },
            detail = "resolved node enabled=${selected.enabled} " +
                "expected=${predicate.expectedEnabled}",
            resolution = resolution,
        )
    }

    private fun unresolvedPredicate(resolution: SelectorResolution): PredicateEvaluation =
        PredicateEvaluation(
            outcome = when (resolution.outcome) {
                SelectorResolutionOutcome.NOT_FOUND -> PredicateOutcome.UNSATISFIED
                SelectorResolutionOutcome.AMBIGUOUS,
                SelectorResolutionOutcome.INVALID_SELECTOR,
                -> PredicateOutcome.INDETERMINATE
                SelectorResolutionOutcome.RESOLVED -> PredicateOutcome.INDETERMINATE
            },
            detail = resolution.detail,
            resolution = resolution,
        )
}
