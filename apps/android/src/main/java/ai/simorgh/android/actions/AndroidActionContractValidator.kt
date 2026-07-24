package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.ScreenBounds
import java.util.UUID

object AndroidActionContractValidator {
    fun validate(command: AndroidActionCommand): AndroidActionCommand {
        command.validated()
        requireUuid(command.commandId, "command_id")
        requireUuid(command.actionId, "action_id")
        validatePrecondition(command.precondition)
        validateOperation(command.operation)
        validateVerification(command.verification)
        return command
    }

    fun validate(result: AndroidActionResult): AndroidActionResult {
        require(result.schemaVersion == ACTION_SCHEMA_VERSION) {
            "unsupported action result schema version"
        }
        requireUuid(result.commandId, "command_id")
        requireUuid(result.actionId, "action_id")
        require(result.startedAtMs >= 0) { "started_at_ms cannot be negative" }
        require(result.finishedAtMs >= result.startedAtMs) {
            "finished_at_ms cannot precede started_at_ms"
        }
        require(result.attempts in 0..5) { "attempts must be in 0..5" }
        require(result.detail.length <= 2_000) { "result detail exceeds 2000 characters" }
        require(result.predicates.size <= 10) { "result predicates exceed 10 entries" }
        require(
            (result.outcome == ActionOutcome.SUCCEEDED) ==
                (result.failureCode == ActionFailureCode.NONE),
        ) {
            "successful results require failure_code=none; failures require a typed code"
        }
        result.beforeObservation?.let(::validateObservationReference)
        result.afterObservation?.let(::validateObservationReference)
        result.resolution?.let(::validateResolutionEvidence)
        result.predicates.forEach(::validatePredicateEvidence)
        return result
    }

    private fun validatePrecondition(precondition: ObservationPrecondition) {
        precondition.validated()
        precondition.expectedStreamId?.let { value -> requireUuid(value, "expected_stream_id") }
        precondition.expectedActivePackage?.let { packageName ->
            require(packageName.isNotBlank() && packageName.length <= 512) {
                "expected_active_package is invalid"
            }
        }
    }

    private fun validateOperation(operation: AndroidOperation) {
        when (operation) {
            is OpenAppOperation -> {
                requireBoundedNonBlank(operation.packageName, 512, "open_app package_name")
                operation.uri?.let { uri ->
                    requireBoundedNonBlank(uri, 4_096, "open_app uri")
                }
            }

            is ClickNodeOperation -> {
                require(operation.selectors.size in 1..5) {
                    "click_node requires 1..5 selectors"
                }
                operation.selectors.forEach(::validateSelector)
            }

            is SetTextOperation -> {
                require(operation.selectors.size in 1..5) {
                    "set_text requires 1..5 selectors"
                }
                require(operation.text.length <= 10_000) {
                    "set_text text exceeds 10000 characters"
                }
                operation.selectors.forEach(::validateSelector)
            }

            is ScrollNodeOperation -> {
                require(operation.selectors.size in 1..5) {
                    "scroll_node requires 1..5 selectors"
                }
                require(operation.amount > 0.0 && operation.amount <= 1.0) {
                    "scroll amount must be in (0, 1]"
                }
                operation.selectors.forEach(::validateSelector)
            }

            is GlobalActionOperation -> Unit
            is WaitOperation -> require(operation.durationMs in 50..10_000) {
                "wait duration_ms must be in 50..10000"
            }
        }
    }

    private fun validateVerification(policy: AndroidVerificationPolicy) {
        require(policy.predicates.size in 1..10) {
            "verification requires 1..10 predicates"
        }
        require(policy.timeoutMs in 250..30_000) {
            "verification timeout_ms must be in 250..30000"
        }
        require(policy.stableSamples in 1..3) {
            "verification stable_samples must be in 1..3"
        }
        policy.predicates.forEach(::validatePredicate)
    }

    private fun validatePredicate(predicate: UiPredicate) {
        when (predicate) {
            is ActivePackageEqualsPredicate ->
                requireBoundedNonBlank(predicate.packageName, 512, "predicate package_name")
            is NodeExistsPredicate -> validateSelector(predicate.selector)
            is NodeAbsentPredicate -> validateSelector(predicate.selector)
            is NodeTextEqualsPredicate -> {
                validateSelector(predicate.selector)
                require(predicate.expectedText.length <= 512) {
                    "predicate expected_text exceeds 512 characters"
                }
            }
            is NodeCheckedEqualsPredicate -> validateSelector(predicate.selector)
            is NodeEnabledEqualsPredicate -> validateSelector(predicate.selector)
        }
    }

    private fun validateSelector(selector: AndroidNodeSelector) {
        selector.validated()
        selector.viewId?.let { value ->
            requireBoundedNonBlank(value, 512, "selector view_id")
        }
        selector.className?.let { value ->
            requireBoundedNonBlank(value, 512, "selector class_name")
        }
        selector.path?.let { value ->
            require(value.length <= 512) { "selector path exceeds 512 characters" }
        }
        selector.bounds?.let(::validateBounds)
        require(selector.requiredFields.size <= 7) {
            "selector required_fields exceed 7 entries"
        }
        require(selector.requiredCapabilities.size <= 6) {
            "selector required_capabilities exceed 6 entries"
        }
    }

    private fun validateBounds(bounds: ScreenBounds) {
        require(bounds.right >= bounds.left && bounds.bottom >= bounds.top) {
            "selector bounds must have non-negative width and height"
        }
    }

    private fun validateObservationReference(reference: ObservationReference) {
        requireUuid(reference.streamId, "observation stream_id")
        requireUuid(reference.snapshotId, "observation snapshot_id")
        require(reference.sequence >= 0) { "observation sequence cannot be negative" }
        require(reference.capturedAtMs >= 0) { "observation captured_at_ms cannot be negative" }
        requireHex(reference.stateFingerprint, 64, "observation state_fingerprint")
        reference.activePackage?.let { packageName ->
            require(packageName.length <= 512) { "observation active_package exceeds 512" }
        }
    }

    private fun validateResolutionEvidence(evidence: SelectorResolutionEvidence) {
        require(
            evidence.outcome in setOf(
                "resolved",
                "not_found",
                "ambiguous",
                "invalid_selector",
            ),
        ) { "selector resolution outcome is invalid" }
        evidence.selectedNodeId?.let { nodeId ->
            requireHex(nodeId, 24, "selected_node_id")
        }
        evidence.selectedPath?.let { path ->
            require(path.length <= 512) { "selected_path exceeds 512 characters" }
        }
        require(evidence.selectedScore == null || evidence.selectedScore >= 0) {
            "selected_score cannot be negative"
        }
        require(evidence.scoreMargin == null || evidence.scoreMargin >= 0) {
            "score_margin cannot be negative"
        }
        require(evidence.candidates.size <= 5) { "resolution candidates exceed 5" }
        evidence.candidates.forEach(::validateCandidateEvidence)
    }

    private fun validateCandidateEvidence(evidence: SelectorCandidateEvidence) {
        requireHex(evidence.nodeId, 24, "candidate node_id")
        requireBoundedNonBlank(evidence.path, 512, "candidate path")
        require(evidence.score >= 0) { "candidate score cannot be negative" }
        require(evidence.matchedSignals.size <= 32) {
            "candidate matched_signals exceed 32"
        }
    }

    private fun validatePredicateEvidence(evidence: PredicateEvidence) {
        requireBoundedNonBlank(evidence.kind, 128, "predicate evidence kind")
        require(evidence.detail.length <= 1_000) {
            "predicate evidence detail exceeds 1000 characters"
        }
        evidence.resolution?.let(::validateResolutionEvidence)
    }

    private fun requireUuid(value: String, field: String) {
        require(runCatching { UUID.fromString(value) }.isSuccess) { "$field must be a UUID" }
    }

    private fun requireHex(value: String, length: Int, field: String) {
        require(value.length == length && value.all(::isLowercaseHex)) {
            "$field must be $length lowercase hexadecimal characters"
        }
    }

    private fun isLowercaseHex(character: Char): Boolean =
        character in '0'..'9' || character in 'a'..'f'

    private fun requireBoundedNonBlank(value: String, maximum: Int, field: String) {
        require(value.isNotBlank() && value.length <= maximum) { "$field is invalid" }
    }
}
