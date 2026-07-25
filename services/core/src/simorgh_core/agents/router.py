from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from simorgh_core.agents.budget import (
    BudgetAccount,
    BudgetCancelledError,
    BudgetElapsedError,
    BudgetExceededError,
)
from simorgh_core.agents.contracts import (
    AgentClassification,
    RoutingDecision,
    RoutingMethod,
    RoutingRule,
    RoutingState,
    SpecialistDefinition,
    TaskEnvelope,
)
from simorgh_core.agents.invocations import stable_invocation_id
from simorgh_core.agents.registry import SpecialistRegistry

_WHITESPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\u0600-\u06ff]+", flags=re.UNICODE)
_PERSIAN_TRANSLATION = str.maketrans(
    {
        "\u064a": "\u06cc",  # Arabic yeh -> Persian yeh
        "\u0649": "\u06cc",  # alef maksura -> Persian yeh
        "\u0643": "\u06a9",  # Arabic kaf -> Persian kaf
        "\u0629": "\u0647",  # teh marbuta -> heh
        "\u06c0": "\u0647",  # heh with yeh above -> heh
        "\u0624": "\u0648",  # waw with hamza -> waw
        "\u0625": "\u0627",  # alef with hamza below -> alef
        "\u0623": "\u0627",  # alef with hamza above -> alef
        "\u0671": "\u0627",  # alef wasla -> alef
        "\u200c": " ",  # zero-width non-joiner
        "\u200d": " ",  # zero-width joiner
    }
)
_ROUTER_AGENT_ID = "system.specialist-router"
_ROUTER_VERSION = "1.0.0"


class AgentClassifier(Protocol):
    """One bounded semantic classification call; implementations own reservation/replay."""

    async def classify(
        self,
        *,
        task: TaskEnvelope,
        candidates: Sequence[SpecialistDefinition],
        budget: BudgetAccount,
        invocation_id: UUID,
    ) -> AgentClassification: ...


class SpecialistRouter:
    """Route explicitly and lexically before permitting one model classification."""

    def __init__(
        self,
        *,
        registry: SpecialistRegistry,
        classifier: AgentClassifier | None = None,
        minimum_classifier_confidence_bps: int = 7_000,
    ) -> None:
        if minimum_classifier_confidence_bps not in range(0, 10_001):
            raise ValueError("classifier confidence threshold must be in 0..10000")
        self._registry = registry
        self._classifier = classifier
        self._minimum_classifier_confidence_bps = minimum_classifier_confidence_bps

    async def route(
        self,
        *,
        task: TaskEnvelope,
        budget: BudgetAccount,
    ) -> RoutingDecision:
        candidates = self._registry.eligible(task)
        candidate_ids = tuple(candidate.agent_id for candidate in candidates)
        if not candidates:
            return RoutingDecision(
                request_id=task.request_id,
                state=RoutingState.POLICY_BLOCKED,
                candidate_agent_ids=(),
                reason=(
                    "no registered specialist is compatible with the task kind, locale, "
                    "and execution-mode policy"
                ),
            )

        if task.explicit_task_kind is not None:
            explicit = self._resolve_unique_priority(candidates)
            if explicit is not None:
                return self._routed(
                    task=task,
                    definition=explicit,
                    method=RoutingMethod.EXPLICIT_TASK_KIND,
                    confidence_bps=10_000,
                    candidate_ids=candidate_ids,
                    matched_rule_ids=(),
                    reason=(
                        f"explicit task kind {task.explicit_task_kind.value!r} has one "
                        "highest-priority compatible specialist"
                    ),
                )

        scores = self._score_rules(task=task, candidates=candidates)
        positive = [score for score in scores if score.score > 0]
        if positive:
            positive.sort(
                key=lambda score: (
                    -score.score,
                    score.definition.routing_priority,
                    score.definition.agent_id,
                )
            )
            highest = positive[0]
            tied = [score for score in positive if score.score == highest.score]
            if len(tied) == 1:
                confidence = min(9_900, 7_500 + highest.score * 25)
                return self._routed(
                    task=task,
                    definition=highest.definition,
                    method=RoutingMethod.DETERMINISTIC_RULE,
                    confidence_bps=confidence,
                    candidate_ids=candidate_ids,
                    matched_rule_ids=highest.rule_ids,
                    reason=(
                        f"deterministic lexical rules selected {highest.definition.agent_id!r} "
                        f"with score {highest.score}"
                    ),
                )

        if self._classifier is None:
            return RoutingDecision(
                request_id=task.request_id,
                state=RoutingState.NEEDS_CLARIFICATION,
                candidate_agent_ids=candidate_ids,
                matched_rule_ids=tuple(
                    sorted(
                        {
                            rule_id
                            for score in positive
                            for rule_id in score.rule_ids
                        }
                    )
                ),
                reason=(
                    "deterministic routing did not produce one unique specialist and no "
                    "bounded semantic classifier is configured"
                ),
            )

        invocation_id = stable_invocation_id(
            request_id=task.request_id,
            agent_id=_ROUTER_AGENT_ID,
            agent_version=_ROUTER_VERSION,
            operation="classify-primary-specialist",
        )
        try:
            classification = await self._classifier.classify(
                task=task,
                candidates=candidates,
                budget=budget,
                invocation_id=invocation_id,
            )
        except (BudgetExceededError, BudgetElapsedError, BudgetCancelledError) as exc:
            return RoutingDecision(
                request_id=task.request_id,
                state=RoutingState.BUDGET_EXHAUSTED,
                method=RoutingMethod.MODEL_CLASSIFIER,
                candidate_agent_ids=candidate_ids,
                classifier_invocation_id=invocation_id,
                model_calls=1,
                reason=f"semantic routing could not reserve or use budget: {exc}",
            )

        selected = next(
            (
                definition
                for definition in candidates
                if definition.agent_id == classification.selected_agent_id
            ),
            None,
        )
        if selected is None:
            return RoutingDecision(
                request_id=task.request_id,
                state=RoutingState.CONTRACT_INVALID,
                method=RoutingMethod.MODEL_CLASSIFIER,
                candidate_agent_ids=candidate_ids,
                classifier_invocation_id=invocation_id,
                model_calls=1,
                reason=(
                    "classifier selected an agent outside the eligible candidate set: "
                    f"{classification.selected_agent_id!r}"
                ),
            )
        if classification.confidence_bps < self._minimum_classifier_confidence_bps:
            return RoutingDecision(
                request_id=task.request_id,
                state=RoutingState.NEEDS_CLARIFICATION,
                method=RoutingMethod.MODEL_CLASSIFIER,
                confidence_bps=classification.confidence_bps,
                candidate_agent_ids=candidate_ids,
                classifier_invocation_id=invocation_id,
                model_calls=1,
                reason=(
                    f"classifier confidence {classification.confidence_bps}bps is below "
                    f"{self._minimum_classifier_confidence_bps}bps: {classification.reason}"
                ),
            )
        return self._routed(
            task=task,
            definition=selected,
            method=RoutingMethod.MODEL_CLASSIFIER,
            confidence_bps=classification.confidence_bps,
            candidate_ids=candidate_ids,
            matched_rule_ids=(),
            classifier_invocation_id=invocation_id,
            model_calls=1,
            reason=classification.reason,
        )

    def _score_rules(
        self,
        *,
        task: TaskEnvelope,
        candidates: Sequence[SpecialistDefinition],
    ) -> list[_RuleScore]:
        normalized_text = normalize_routing_text(
            f"{task.input_text}\n{task.requested_outcome}"
        )
        scores: list[_RuleScore] = []
        for definition in candidates:
            score = 0
            rule_ids: list[str] = []
            for rule in definition.routing_rules:
                if not self._rule_locale_matches(rule=rule, locale=task.locale):
                    continue
                matches = sum(
                    1
                    for phrase in rule.phrases
                    if normalize_routing_text(phrase) in normalized_text
                )
                if matches:
                    score += rule.weight * matches
                    rule_ids.append(rule.rule_id)
            scores.append(
                _RuleScore(
                    definition=definition,
                    score=score,
                    rule_ids=tuple(sorted(rule_ids)),
                )
            )
        return scores

    @staticmethod
    def _resolve_unique_priority(
        candidates: Sequence[SpecialistDefinition],
    ) -> SpecialistDefinition | None:
        if len(candidates) == 1:
            return candidates[0]
        lowest_priority = min(candidate.routing_priority for candidate in candidates)
        highest_priority = [
            candidate
            for candidate in candidates
            if candidate.routing_priority == lowest_priority
        ]
        return highest_priority[0] if len(highest_priority) == 1 else None

    @staticmethod
    def _rule_locale_matches(*, rule: RoutingRule, locale: str) -> bool:
        if not rule.locale_prefixes:
            return True
        normalized = locale.casefold()
        return any(
            normalized.startswith(prefix.casefold())
            for prefix in rule.locale_prefixes
        )

    @staticmethod
    def _routed(
        *,
        task: TaskEnvelope,
        definition: SpecialistDefinition,
        method: RoutingMethod,
        confidence_bps: int,
        candidate_ids: tuple[str, ...],
        matched_rule_ids: tuple[str, ...],
        reason: str,
        classifier_invocation_id: UUID | None = None,
        model_calls: int = 0,
    ) -> RoutingDecision:
        return RoutingDecision(
            request_id=task.request_id,
            state=RoutingState.ROUTED,
            selected_agent_id=definition.agent_id,
            selected_agent_version=definition.version,
            method=method,
            confidence_bps=confidence_bps,
            candidate_agent_ids=candidate_ids,
            matched_rule_ids=matched_rule_ids,
            classifier_invocation_id=classifier_invocation_id,
            model_calls=model_calls,
            reason=reason,
        )


class _RuleScore:
    __slots__ = ("definition", "rule_ids", "score")

    def __init__(
        self,
        *,
        definition: SpecialistDefinition,
        score: int,
        rule_ids: tuple[str, ...],
    ) -> None:
        self.definition = definition
        self.score = score
        self.rule_ids = rule_ids


def normalize_routing_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).translate(_PERSIAN_TRANSLATION)
    normalized = normalized.casefold()
    normalized = _NON_WORD.sub(" ", normalized)
    return _WHITESPACE.sub(" ", normalized).strip()
