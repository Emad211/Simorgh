package ai.simorgh.android.actions

import ai.simorgh.android.accessibility.ScreenBounds
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

const val ACTION_SCHEMA_VERSION: String = "1.0"

@Serializable
enum class TextMatchMode {
    @SerialName("exact")
    EXACT,

    @SerialName("contains")
    CONTAINS,
}

@Serializable
enum class SelectorField {
    @SerialName("view_id")
    VIEW_ID,

    @SerialName("text")
    TEXT,

    @SerialName("content_description")
    CONTENT_DESCRIPTION,

    @SerialName("class_name")
    CLASS_NAME,

    @SerialName("path")
    PATH,

    @SerialName("semantic_fingerprint")
    SEMANTIC_FINGERPRINT,

    @SerialName("bounds")
    BOUNDS,
}

@Serializable
enum class NodeCapability {
    @SerialName("clickable")
    CLICKABLE,

    @SerialName("long_clickable")
    LONG_CLICKABLE,

    @SerialName("editable")
    EDITABLE,

    @SerialName("scrollable")
    SCROLLABLE,

    @SerialName("checkable")
    CHECKABLE,

    @SerialName("focusable")
    FOCUSABLE,
}

@Serializable
enum class ScrollDirection {
    @SerialName("up")
    UP,

    @SerialName("down")
    DOWN,

    @SerialName("left")
    LEFT,

    @SerialName("right")
    RIGHT,

    @SerialName("forward")
    FORWARD,

    @SerialName("backward")
    BACKWARD,
}

@Serializable
enum class GlobalActionName {
    @SerialName("back")
    BACK,

    @SerialName("home")
    HOME,

    @SerialName("recents")
    RECENTS,
}

@Serializable
enum class ActionOutcome {
    @SerialName("succeeded")
    SUCCEEDED,

    @SerialName("failed")
    FAILED,

    @SerialName("blocked")
    BLOCKED,

    @SerialName("timed_out")
    TIMED_OUT,

    @SerialName("cancelled")
    CANCELLED,
}

@Serializable
enum class ActionFailureCode {
    @SerialName("none")
    NONE,

    @SerialName("invalid_command")
    INVALID_COMMAND,

    @SerialName("expired")
    EXPIRED,

    @SerialName("precondition_failed")
    PRECONDITION_FAILED,

    @SerialName("unsupported_capability")
    UNSUPPORTED_CAPABILITY,

    @SerialName("target_not_found")
    TARGET_NOT_FOUND,

    @SerialName("target_ambiguous")
    TARGET_AMBIGUOUS,

    @SerialName("action_rejected")
    ACTION_REJECTED,

    @SerialName("postcondition_failed")
    POSTCONDITION_FAILED,

    @SerialName("observation_timeout")
    OBSERVATION_TIMEOUT,

    @SerialName("cancelled")
    CANCELLED,

    @SerialName("internal_error")
    INTERNAL_ERROR,
}

@Serializable
enum class PredicateOutcome {
    @SerialName("satisfied")
    SATISFIED,

    @SerialName("unsatisfied")
    UNSATISFIED,

    @SerialName("indeterminate")
    INDETERMINATE,
}

@Serializable
data class TextCriterion(
    val value: String,
    val mode: TextMatchMode = TextMatchMode.EXACT,
    @SerialName("case_sensitive")
    val caseSensitive: Boolean = false,
) {
    fun validated(): TextCriterion = apply {
        require(value.isNotBlank()) { "text criterion cannot be blank" }
        require(value.length <= 512) { "text criterion exceeds 512 characters" }
    }
}

@Serializable
data class AndroidNodeSelector(
    @SerialName("package_name")
    val packageName: String,
    @SerialName("view_id")
    val viewId: String? = null,
    val text: TextCriterion? = null,
    @SerialName("content_description")
    val contentDescription: TextCriterion? = null,
    @SerialName("class_name")
    val className: String? = null,
    val path: String? = null,
    @SerialName("semantic_fingerprint")
    val semanticFingerprint: String? = null,
    val bounds: ScreenBounds? = null,
    @SerialName("required_fields")
    val requiredFields: Set<SelectorField> = emptySet(),
    @SerialName("required_capabilities")
    val requiredCapabilities: Set<NodeCapability> = emptySet(),
    @SerialName("minimum_score")
    val minimumScore: Int = 80,
    @SerialName("minimum_margin")
    val minimumMargin: Int = 20,
) {
    fun validated(): AndroidNodeSelector {
        require(packageName.isNotBlank() && packageName.length <= 512) {
            "selector package_name is invalid"
        }
        require(minimumScore in 1..500) { "minimum_score must be in 1..500" }
        require(minimumMargin in 0..500) { "minimum_margin must be in 0..500" }
        text?.validated()
        contentDescription?.validated()
        require(path == null || PATH_REGEX.matches(path)) { "selector path is invalid" }
        require(
            semanticFingerprint == null ||
                (semanticFingerprint.length == 24 && HEX_REGEX.matches(semanticFingerprint)),
        ) { "selector semantic_fingerprint is invalid" }

        val present = presentFields()
        require(present.isNotEmpty()) { "selector requires at least one identity field" }
        require(requiredFields.all(present::contains)) {
            "required_fields reference fields without values"
        }

        if (requiredFields.isNotEmpty()) {
            return this
        }
        val strongest = SELECTOR_FIELD_PRIORITY.first(present::contains)
        return copy(requiredFields = setOf(strongest))
    }

    fun presentFields(): Set<SelectorField> = buildSet {
        if (viewId != null) add(SelectorField.VIEW_ID)
        if (text != null) add(SelectorField.TEXT)
        if (contentDescription != null) add(SelectorField.CONTENT_DESCRIPTION)
        if (className != null) add(SelectorField.CLASS_NAME)
        if (path != null) add(SelectorField.PATH)
        if (semanticFingerprint != null) add(SelectorField.SEMANTIC_FINGERPRINT)
        if (bounds != null) add(SelectorField.BOUNDS)
    }

    private companion object {
        val PATH_REGEX = Regex("^0(?:\\.[0-9]+)*$")
        val HEX_REGEX = Regex("^[0-9a-f]+$")
        val SELECTOR_FIELD_PRIORITY = listOf(
            SelectorField.VIEW_ID,
            SelectorField.SEMANTIC_FINGERPRINT,
            SelectorField.TEXT,
            SelectorField.CONTENT_DESCRIPTION,
            SelectorField.PATH,
            SelectorField.CLASS_NAME,
            SelectorField.BOUNDS,
        )
    }
}

@Serializable
data class ObservationPrecondition(
    @SerialName("expected_stream_id")
    val expectedStreamId: String? = null,
    @SerialName("minimum_sequence")
    val minimumSequence: Long? = null,
    @SerialName("expected_state_fingerprint")
    val expectedStateFingerprint: String? = null,
    @SerialName("expected_active_package")
    val expectedActivePackage: String? = null,
    @SerialName("maximum_age_ms")
    val maximumAgeMs: Long = 2_000,
) {
    fun validated(): ObservationPrecondition = apply {
        require(minimumSequence == null || minimumSequence >= 0) {
            "minimum_sequence cannot be negative"
        }
        require(maximumAgeMs in 100..30_000) { "maximum_age_ms must be in 100..30000" }
        require(
            expectedStateFingerprint == null ||
                (expectedStateFingerprint.length == 64 && HEX_REGEX.matches(expectedStateFingerprint)),
        ) { "expected_state_fingerprint is invalid" }
    }

    private companion object {
        val HEX_REGEX = Regex("^[0-9a-f]+$")
    }
}

@Serializable
sealed interface AndroidOperation

@Serializable
@SerialName("open_app")
data class OpenAppOperation(
    @SerialName("package_name")
    val packageName: String,
    val uri: String? = null,
) : AndroidOperation

@Serializable
@SerialName("click_node")
data class ClickNodeOperation(
    val selectors: List<AndroidNodeSelector>,
    @SerialName("allow_gesture_fallback")
    val allowGestureFallback: Boolean = true,
) : AndroidOperation

@Serializable
@SerialName("set_text")
data class SetTextOperation(
    val selectors: List<AndroidNodeSelector>,
    val text: String,
) : AndroidOperation

@Serializable
@SerialName("scroll_node")
data class ScrollNodeOperation(
    val selectors: List<AndroidNodeSelector>,
    val direction: ScrollDirection,
    val amount: Double = 0.7,
    @SerialName("allow_gesture_fallback")
    val allowGestureFallback: Boolean = true,
) : AndroidOperation

@Serializable
@SerialName("global_action")
data class GlobalActionOperation(
    val action: GlobalActionName,
) : AndroidOperation

@Serializable
@SerialName("wait")
data class WaitOperation(
    @SerialName("duration_ms")
    val durationMs: Long,
) : AndroidOperation

@Serializable
sealed interface UiPredicate

@Serializable
@SerialName("active_package_equals")
data class ActivePackageEqualsPredicate(
    @SerialName("package_name")
    val packageName: String,
) : UiPredicate

@Serializable
@SerialName("node_exists")
data class NodeExistsPredicate(
    val selector: AndroidNodeSelector,
) : UiPredicate

@Serializable
@SerialName("node_absent")
data class NodeAbsentPredicate(
    val selector: AndroidNodeSelector,
) : UiPredicate

@Serializable
@SerialName("node_text_equals")
data class NodeTextEqualsPredicate(
    val selector: AndroidNodeSelector,
    @SerialName("expected_text")
    val expectedText: String,
    @SerialName("case_sensitive")
    val caseSensitive: Boolean = false,
) : UiPredicate

@Serializable
@SerialName("node_checked_equals")
data class NodeCheckedEqualsPredicate(
    val selector: AndroidNodeSelector,
    @SerialName("expected_checked")
    val expectedChecked: Boolean,
) : UiPredicate

@Serializable
@SerialName("node_enabled_equals")
data class NodeEnabledEqualsPredicate(
    val selector: AndroidNodeSelector,
    @SerialName("expected_enabled")
    val expectedEnabled: Boolean,
) : UiPredicate

@Serializable
data class AndroidVerificationPolicy(
    val predicates: List<UiPredicate>,
    @SerialName("timeout_ms")
    val timeoutMs: Long = 10_000,
    @SerialName("stable_samples")
    val stableSamples: Int = 1,
)

@Serializable
data class AndroidActionCommand(
    @SerialName("schema_version")
    val schemaVersion: String = ACTION_SCHEMA_VERSION,
    @SerialName("command_id")
    val commandId: String,
    @SerialName("action_id")
    val actionId: String,
    @SerialName("issued_at_ms")
    val issuedAtMs: Long,
    @SerialName("deadline_at_ms")
    val deadlineAtMs: Long,
    val precondition: ObservationPrecondition,
    val operation: AndroidOperation,
    val verification: AndroidVerificationPolicy,
) {
    fun validated(): AndroidActionCommand = apply {
        require(schemaVersion == ACTION_SCHEMA_VERSION) { "unsupported action schema version" }
        require(deadlineAtMs > issuedAtMs) { "deadline_at_ms must be greater than issued_at_ms" }
        require(deadlineAtMs - issuedAtMs <= 120_000) {
            "Android action command lifetime cannot exceed 120 seconds"
        }
        precondition.validated()
        require(verification.predicates inSizeRange 1..10) {
            "verification requires 1..10 predicates"
        }
        require(verification.timeoutMs in 250..30_000) {
            "verification timeout_ms must be in 250..30000"
        }
        require(verification.stableSamples in 1..3) {
            "stable_samples must be in 1..3"
        }
        validateOperation(operation)
    }

    private fun validateOperation(value: AndroidOperation) {
        when (value) {
            is OpenAppOperation -> {
                require(value.packageName.isNotBlank() && value.packageName.length <= 512)
                require(value.uri == null || value.uri.length <= 4_096)
            }

            is ClickNodeOperation -> {
                require(value.selectors inSizeRange 1..5)
                value.selectors.forEach(AndroidNodeSelector::validated)
            }

            is SetTextOperation -> {
                require(value.selectors inSizeRange 1..5)
                require(value.text.length <= 10_000)
                value.selectors.forEach(AndroidNodeSelector::validated)
            }

            is ScrollNodeOperation -> {
                require(value.selectors inSizeRange 1..5)
                require(value.amount > 0 && value.amount <= 1)
                value.selectors.forEach(AndroidNodeSelector::validated)
            }

            is GlobalActionOperation -> Unit
            is WaitOperation -> require(value.durationMs in 50..10_000)
        }
    }
}

@Serializable
data class ObservationReference(
    @SerialName("stream_id")
    val streamId: String,
    val sequence: Long,
    @SerialName("snapshot_id")
    val snapshotId: String,
    @SerialName("state_fingerprint")
    val stateFingerprint: String,
    @SerialName("captured_at_ms")
    val capturedAtMs: Long,
    @SerialName("active_package")
    val activePackage: String? = null,
)

@Serializable
data class SelectorCandidateEvidence(
    @SerialName("node_id")
    val nodeId: String,
    val path: String,
    val score: Int,
    @SerialName("matched_signals")
    val matchedSignals: List<String> = emptyList(),
)

@Serializable
data class SelectorResolutionEvidence(
    val outcome: String,
    @SerialName("selected_node_id")
    val selectedNodeId: String? = null,
    @SerialName("selected_path")
    val selectedPath: String? = null,
    @SerialName("selected_score")
    val selectedScore: Int? = null,
    @SerialName("score_margin")
    val scoreMargin: Int? = null,
    val candidates: List<SelectorCandidateEvidence> = emptyList(),
)

@Serializable
data class PredicateEvidence(
    val kind: String,
    val outcome: PredicateOutcome,
    val detail: String,
    val resolution: SelectorResolutionEvidence? = null,
)

@Serializable
data class AndroidActionResult(
    @SerialName("schema_version")
    val schemaVersion: String = ACTION_SCHEMA_VERSION,
    @SerialName("command_id")
    val commandId: String,
    @SerialName("action_id")
    val actionId: String,
    val outcome: ActionOutcome,
    @SerialName("failure_code")
    val failureCode: ActionFailureCode = ActionFailureCode.NONE,
    @SerialName("started_at_ms")
    val startedAtMs: Long,
    @SerialName("finished_at_ms")
    val finishedAtMs: Long,
    val attempts: Int = 1,
    @SerialName("before_observation")
    val beforeObservation: ObservationReference? = null,
    @SerialName("after_observation")
    val afterObservation: ObservationReference? = null,
    val resolution: SelectorResolutionEvidence? = null,
    val predicates: List<PredicateEvidence> = emptyList(),
    val detail: String = "",
)

object AndroidActionJson {
    val codec: Json = Json {
        encodeDefaults = true
        explicitNulls = false
        ignoreUnknownKeys = false
        classDiscriminator = "kind"
    }
}

private infix fun <T> Collection<T>.inSizeRange(range: IntRange): Boolean = size in range
