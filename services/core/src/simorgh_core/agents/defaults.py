from __future__ import annotations

from simorgh_core.agents.contracts import (
    ModelPolicy,
    ModelTier,
    RoutingRule,
    SideEffectPolicy,
    SpecialistDefinition,
    TaskBudget,
    TaskKind,
)
from simorgh_core.agents.registry import SpecialistRegistry

_READ_BUDGET = TaskBudget(
    max_model_calls=1,
    max_tool_calls=6,
    max_input_tokens=24_000,
    max_output_tokens=4_000,
    max_estimated_cost_microusd=40_000,
    max_elapsed_ms=120_000,
    max_retries=1,
    max_parallel_branches=1,
)
_LIVE_PROVIDER_STAGING_BUDGET = TaskBudget(
    max_model_calls=1,
    max_tool_calls=0,
    max_input_tokens=128,
    max_output_tokens=16,
    max_estimated_cost_microusd=20_000,
    max_elapsed_ms=60_000,
    max_retries=0,
    max_parallel_branches=1,
)
_PLANNING_BUDGET = TaskBudget(
    max_model_calls=2,
    max_tool_calls=8,
    max_input_tokens=48_000,
    max_output_tokens=8_000,
    max_estimated_cost_microusd=150_000,
    max_elapsed_ms=240_000,
    max_retries=1,
    max_parallel_branches=2,
)
_READ_MODEL_POLICY = ModelPolicy(
    allowed_tiers=(ModelTier.FAST, ModelTier.GENERAL),
    minimum_tier=ModelTier.FAST,
    maximum_model_calls=1,
)
_LIVE_PROVIDER_STAGING_MODEL_POLICY = ModelPolicy(
    allowed_tiers=(ModelTier.FAST,),
    minimum_tier=ModelTier.FAST,
    maximum_model_calls=1,
)
_PLANNING_MODEL_POLICY = ModelPolicy(
    allowed_tiers=(ModelTier.FAST, ModelTier.GENERAL, ModelTier.REASONING),
    minimum_tier=ModelTier.FAST,
    maximum_model_calls=2,
)


def default_specialist_registry() -> SpecialistRegistry:
    return SpecialistRegistry(default_specialist_definitions())


def default_specialist_definitions() -> tuple[SpecialistDefinition, ...]:
    return (
        SpecialistDefinition(
            agent_id="system.live-provider-staging",
            version="1.0.0",
            display_name="Protected Live Provider Staging Agent",
            task_kinds=frozenset({TaskKind.LIVE_PROVIDER_STAGING}),
            locale_prefixes=frozenset({"en"}),
            input_contract="simorgh.task.v1",
            output_contract="simorgh.live-provider-staging.v1",
            tool_allowlist=frozenset(),
            connector_allowlist=frozenset(),
            model_policy=_LIVE_PROVIDER_STAGING_MODEL_POLICY,
            budget_ceiling=_LIVE_PROVIDER_STAGING_BUDGET,
            side_effect_policy=SideEffectPolicy.NONE,
            routing_rules=(),
            routing_priority=5,
        ),
        SpecialistDefinition(
            agent_id="github.read",
            version="1.0.0",
            display_name="GitHub Research Agent",
            task_kinds=frozenset({TaskKind.REPOSITORY_RESEARCH}),
            locale_prefixes=frozenset({"fa", "en"}),
            input_contract="simorgh.task.v1",
            output_contract="simorgh.repository-report.v1",
            tool_allowlist=frozenset(
                {
                    "github.search",
                    "github.fetch-file",
                    "github.fetch-issue",
                    "github.fetch-pr",
                }
            ),
            connector_allowlist=frozenset({"github"}),
            model_policy=_READ_MODEL_POLICY,
            budget_ceiling=_READ_BUDGET,
            side_effect_policy=SideEffectPolicy.NONE,
            routing_rules=(
                RoutingRule(
                    rule_id="github.explicit-terms",
                    locale_prefixes=frozenset({"fa", "en"}),
                    phrases=(
                        "github",
                        "گیت هاب",
                        "گیتهاب",
                        "ریپازیتوری",
                        "repository",
                        "pull request",
                        "پول ریکوئست",
                        "github issue",
                    ),
                    weight=30,
                ),
            ),
            routing_priority=10,
        ),
        SpecialistDefinition(
            agent_id="development.planner",
            version="1.0.0",
            display_name="Software Development Planning Agent",
            task_kinds=frozenset({TaskKind.DEVELOPMENT_PLANNING}),
            locale_prefixes=frozenset({"fa", "en"}),
            input_contract="simorgh.task.v1",
            output_contract="simorgh.typed-plan.v1",
            tool_allowlist=frozenset(
                {
                    "github.search",
                    "github.fetch-file",
                    "docs.read",
                }
            ),
            connector_allowlist=frozenset({"github"}),
            model_policy=_PLANNING_MODEL_POLICY,
            budget_ceiling=_PLANNING_BUDGET,
            side_effect_policy=SideEffectPolicy.PROPOSE_ONLY,
            routing_rules=(
                RoutingRule(
                    rule_id="development.implementation-terms",
                    locale_prefixes=frozenset({"fa", "en"}),
                    phrases=(
                        "برنامه نویسی",
                        "توسعه نرم افزار",
                        "کدنویسی",
                        "معماری سیستم",
                        "باگ",
                        "api",
                        "backend",
                        "frontend",
                        "database",
                        "پیاده سازی",
                        "implement",
                        "debug",
                    ),
                    weight=18,
                ),
            ),
            routing_priority=20,
        ),
        SpecialistDefinition(
            agent_id="seo.planner",
            version="1.0.0",
            display_name="SEO Strategy Agent",
            task_kinds=frozenset({TaskKind.SEO_PLANNING}),
            locale_prefixes=frozenset({"fa", "en"}),
            input_contract="simorgh.task.v1",
            output_contract="simorgh.typed-plan.v1",
            tool_allowlist=frozenset(
                {
                    "web.search",
                    "analytics.read",
                    "search-console.read",
                }
            ),
            connector_allowlist=frozenset(
                {"web", "analytics", "search-console"}
            ),
            model_policy=_PLANNING_MODEL_POLICY,
            budget_ceiling=_PLANNING_BUDGET,
            side_effect_policy=SideEffectPolicy.PROPOSE_ONLY,
            routing_rules=(
                RoutingRule(
                    rule_id="seo.core-terms",
                    locale_prefixes=frozenset({"fa", "en"}),
                    phrases=(
                        "seo",
                        "سئو",
                        "کلمه کلیدی",
                        "کیورد",
                        "search console",
                        "سرچ کنسول",
                        "رتبه گوگل",
                        "بک لینک",
                        "technical seo",
                    ),
                    weight=35,
                ),
            ),
            routing_priority=20,
        ),
        SpecialistDefinition(
            agent_id="marketing.planner",
            version="1.0.0",
            display_name="Marketing Strategy Agent",
            task_kinds=frozenset({TaskKind.MARKETING_PLANNING}),
            locale_prefixes=frozenset({"fa", "en"}),
            input_contract="simorgh.task.v1",
            output_contract="simorgh.typed-plan.v1",
            tool_allowlist=frozenset(
                {
                    "web.search",
                    "analytics.read",
                    "crm.read",
                }
            ),
            connector_allowlist=frozenset({"web", "analytics", "crm"}),
            model_policy=_PLANNING_MODEL_POLICY,
            budget_ceiling=_PLANNING_BUDGET,
            side_effect_policy=SideEffectPolicy.PROPOSE_ONLY,
            routing_rules=(
                RoutingRule(
                    rule_id="marketing.core-terms",
                    locale_prefixes=frozenset({"fa", "en"}),
                    phrases=(
                        "مارکتینگ",
                        "بازاریابی",
                        "کمپین",
                        "فروش",
                        "قیف فروش",
                        "تبلیغات",
                        "conversion",
                        "برندینگ",
                        "lead generation",
                    ),
                    weight=24,
                ),
            ),
            routing_priority=25,
        ),
        SpecialistDefinition(
            agent_id="gmail.read",
            version="1.0.0",
            display_name="Email Read Agent",
            task_kinds=frozenset({TaskKind.EMAIL_READ}),
            locale_prefixes=frozenset({"fa", "en"}),
            input_contract="simorgh.task.v1",
            output_contract="simorgh.read-result.v1",
            tool_allowlist=frozenset({"gmail.search", "gmail.read"}),
            connector_allowlist=frozenset({"gmail"}),
            model_policy=_READ_MODEL_POLICY,
            budget_ceiling=_READ_BUDGET,
            side_effect_policy=SideEffectPolicy.NONE,
            routing_rules=(
                RoutingRule(
                    rule_id="gmail.read-terms",
                    locale_prefixes=frozenset({"fa", "en"}),
                    phrases=(
                        "جیمیل",
                        "ایمیل",
                        "صندوق ورودی",
                        "inbox",
                        "gmail",
                        "نامه الکترونیکی",
                    ),
                    weight=28,
                ),
            ),
            routing_priority=15,
        ),
        SpecialistDefinition(
            agent_id="calendar.read",
            version="1.0.0",
            display_name="Calendar Read Agent",
            task_kinds=frozenset({TaskKind.CALENDAR_READ}),
            locale_prefixes=frozenset({"fa", "en"}),
            input_contract="simorgh.task.v1",
            output_contract="simorgh.read-result.v1",
            tool_allowlist=frozenset({"calendar.search", "calendar.availability"}),
            connector_allowlist=frozenset({"google-calendar"}),
            model_policy=_READ_MODEL_POLICY,
            budget_ceiling=_READ_BUDGET,
            side_effect_policy=SideEffectPolicy.NONE,
            routing_rules=(
                RoutingRule(
                    rule_id="calendar.read-terms",
                    locale_prefixes=frozenset({"fa", "en"}),
                    phrases=(
                        "تقویم",
                        "قرار ملاقات",
                        "وقت آزاد",
                        "برنامه امروز",
                        "calendar",
                        "schedule",
                        "availability",
                    ),
                    weight=28,
                ),
            ),
            routing_priority=15,
        ),
        SpecialistDefinition(
            agent_id="drive.read",
            version="1.0.0",
            display_name="Document Read Agent",
            task_kinds=frozenset({TaskKind.DOCUMENT_READ}),
            locale_prefixes=frozenset({"fa", "en"}),
            input_contract="simorgh.task.v1",
            output_contract="simorgh.read-result.v1",
            tool_allowlist=frozenset(
                {"drive.search", "drive.read", "docs.read", "sheets.read"}
            ),
            connector_allowlist=frozenset({"google-drive"}),
            model_policy=_READ_MODEL_POLICY,
            budget_ceiling=_READ_BUDGET,
            side_effect_policy=SideEffectPolicy.NONE,
            routing_rules=(
                RoutingRule(
                    rule_id="drive.read-terms",
                    locale_prefixes=frozenset({"fa", "en"}),
                    phrases=(
                        "گوگل درایو",
                        "google drive",
                        "گوگل داک",
                        "google docs",
                        "سند",
                        "فایل من",
                        "sheet",
                        "spreadsheet",
                    ),
                    weight=24,
                ),
            ),
            routing_priority=20,
        ),
        SpecialistDefinition(
            agent_id="mobile.planner",
            version="1.0.0",
            display_name="Mobile Operation Planning Agent",
            task_kinds=frozenset({TaskKind.MOBILE_OPERATION_PLANNING}),
            locale_prefixes=frozenset({"fa", "en"}),
            input_contract="simorgh.task.v1",
            output_contract="simorgh.mobile-operation-proposal.v1",
            tool_allowlist=frozenset({"device.status", "device.capabilities"}),
            connector_allowlist=frozenset({"simorgh-device"}),
            model_policy=_PLANNING_MODEL_POLICY,
            budget_ceiling=_PLANNING_BUDGET,
            side_effect_policy=SideEffectPolicy.PROPOSE_ONLY,
            routing_rules=(
                RoutingRule(
                    rule_id="mobile.operation-terms",
                    locale_prefixes=frozenset({"fa", "en"}),
                    phrases=(
                        "گوشی",
                        "اندروید",
                        "اپ باز کن",
                        "برنامه را باز کن",
                        "روی موبایل",
                        "android",
                        "open app",
                    ),
                    weight=20,
                ),
            ),
            routing_priority=30,
        ),
        SpecialistDefinition(
            agent_id="general.planner",
            version="1.0.0",
            display_name="General Planning Agent",
            task_kinds=frozenset({TaskKind.GENERAL_PLANNING}),
            locale_prefixes=frozenset({"fa", "en"}),
            input_contract="simorgh.task.v1",
            output_contract="simorgh.typed-plan.v1",
            model_policy=_PLANNING_MODEL_POLICY,
            budget_ceiling=_PLANNING_BUDGET,
            side_effect_policy=SideEffectPolicy.PROPOSE_ONLY,
            routing_rules=(),
            routing_priority=1_000,
        ),
    )
