from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, *, label: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: count={count}, expected=1")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_master_plan() -> None:
    path = "docs/IMPLEMENTATION_MASTER_PLAN.md"
    replace_once(
        path,
        "Phase 1.5 Governed GitHub Read Tools     VALIDATING — PR #52\n"
        "Phase 1.6 Cancellation Propagation       QUEUED\n",
        "Phase 1.5 Governed GitHub Read Tools     COMPLETE — PR #52\n"
        "Phase 1.6 Cancellation Propagation       VALIDATING — PR #54\n",
        label="master current execution position",
    )
    replace_once(
        path,
        "## 1.5 Governed read-only tool execution — VALIDATING\n\n"
        "Implementation is active in PR #52 for issue #51. The product scope remains one read-only GitHub trust boundary; final merge status requires exact-head Core and Android CI plus review audit.\n",
        "## 1.5 Governed read-only tool execution — COMPLETE\n\n"
        "Merged through PR #52 at `7fef6a5262de1e84be89c9afc30c25053945a4ac`. Issue #51 completed; ADR 0018 accepted. The validated implementation head `98f0cc9004e56e76eb9ed1b683099e921ba52d1c` passed CI run `30223753959` with 340 Core tests and full Android build/JVM/lint/APK gates.\n",
        label="master Phase 1.5 completion",
    )
    replace_once(
        path,
        "## 1.6 Cancellation propagation — QUEUED\n\n### Objective\n",
        "## 1.6 Cancellation propagation — VALIDATING\n\n"
        "Implementation is active in PR #54 for issue #53. The current boundary adds durable task-to-invocation ownership, admission fences, conservative reserved-work settlement, optional typed adapter cancellation and privacy-safe audit metadata. Merge still requires exact-head Core/Android CI and review audit.\n\n"
        "### Objective\n",
        label="master Phase 1.6 activation",
    )


def patch_agent_runtime() -> None:
    path = "docs/AGENT_RUNTIME.md"
    replace_once(
        path,
        "Status: typed routing and policy foundation merged in PR #30; durable task authority merged in PR #37; durable invocation authority merged in PR #39; zero-external specialist execution merged in PR #44; typed result/evidence authority merged in PR #48. Phase 1.5 governed GitHub read tools are validating in PR #52. The default API remains routing-only.\n",
        "Status: typed routing and policy foundation merged in PR #30; durable task authority merged in PR #37; durable invocation authority merged in PR #39; zero-external specialist execution merged in PR #44; typed result/evidence authority merged in PR #48; governed GitHub read authority merged in PR #52. Phase 1.6 durable cancellation propagation is validating in PR #54. The default execution API remains routing-only.\n",
        label="runtime status",
    )
    replace_once(
        path,
        "Cancellation is idempotent and survives restart. It marks the task budget cancelled so later work cannot reserve new usage.\n\n"
        "The current runtime has no long-running specialist executor. Complete task-to-child-invocation cancellation enumeration is Phase 1 Step 1.6.\n",
        "Cancellation is idempotent and survives restart. Phase 1.6 first persists the task cancellation request and cancelled budget, then installs a durable invocation fence, captures the exact ownership snapshot, signals registered cooperative owners, settles pending work and handles reserved work with typed proof or conservative uncertainty.\n\n"
        "A reserved read/proposal becomes `cancelled` only when an adapter proves external execution was not entered and releases the reservation; otherwise it becomes `unknown` with conservative committed usage. Reserved mutation always becomes `unknown_side_effect`. Completed results and committed cost remain immutable. See [`CANCELLATION_PROPAGATION.md`](CANCELLATION_PROPAGATION.md) and ADR 0019.\n",
        label="runtime cancellation API semantics",
    )
    replace_once(
        path,
        "## Task phases\n",
        "## Durable cancellation propagation\n\n"
        "The task store remains cancellation source of truth and the invocation store owns a derived fence keyed by `request_id`. Invocation `begin` and `reserve` fail closed after the fence. Work that wins the race before the fence is included in the deterministic ownership snapshot and settled.\n\n"
        "Process-local owner and adapter registries are optional responsiveness mechanisms only. They are exactly-once, late-registration-blocked and empty after restart. Disabling adapter hooks preserves durable fencing, pending cancellation and conservative reserved uncertainty. Audit events contain IDs, states, counts and hashes; operator reason, task content, prompts, connector bodies, exception messages and credentials are excluded.\n\n"
        "## Task phases\n",
        label="runtime cancellation section",
    )
    replace_once(
        path,
        "No automatic retry is enabled.\n",
        "No automatic retry is enabled. Phase 1.6 permits explicit same-task child identity only after a terminal parent and with the exact next attempt number; this ownership relation does not authorize automatic redispatch.\n",
        label="runtime parent-child clarification",
    )


def patch_docs_index() -> None:
    path = "docs/README.md"
    replace_once(
        path,
        "- [`GOVERNED_GITHUB_READ_TOOLS.md`](GOVERNED_GITHUB_READ_TOOLS.md) — exact GitHub read contracts, reviewed manifest, policy intersection, freshness/cache/taint, durable replay and incident handling.\n",
        "- [`GOVERNED_GITHUB_READ_TOOLS.md`](GOVERNED_GITHUB_READ_TOOLS.md) — exact GitHub read contracts, reviewed manifest, policy intersection, freshness/cache/taint, durable replay and incident handling.\n"
        "- [`CANCELLATION_PROPAGATION.md`](CANCELLATION_PROPAGATION.md) — durable task-to-invocation cancellation, ownership fences, conservative uncertainty, adapter acknowledgements, accounting and incident handling.\n",
        label="docs cancellation link",
    )
    replace_once(
        path,
        "The current agent-task API selects one primary owner and persists task/routing state. PR #39 supplies durable invocation authority; PR #44 merged internal zero-external specialist execution; PR #48 merged typed result, artifact and evidence metadata authority. PR #52 is validating governed read-only GitHub tools behind an internal Core boundary. The public API remains routing-only.\n",
        "The current agent-task API selects one primary owner and persists task/routing state. PR #39 supplies durable invocation authority; PR #44 merged internal zero-external specialist execution; PR #48 merged typed result, artifact and evidence metadata authority; PR #52 merged governed read-only GitHub tools. PR #54 is validating durable cancellation propagation across owned invocations. The public execution API remains routing-only.\n",
        label="docs runtime status paragraph",
    )
    replace_once(
        path,
        "- issue #51 — governed read-only GitHub tools and typed evidence, next;\n",
        "- issue #51 / PR #52 — governed read-only GitHub tools and typed evidence, complete;\n"
        "- issue #53 / PR #54 — durable task-to-invocation cancellation propagation, validating;\n",
        label="docs roadmap Phase 1.5 and 1.6",
    )
    replace_once(
        path,
        "- ADR 0018 — governed read-tool authority and typed GitHub evidence.\n",
        "- ADR 0018 — governed read-tool authority and typed GitHub evidence;\n"
        "- ADR 0019 — durable task-to-invocation cancellation propagation.\n",
        label="docs ADR 0019",
    )
    replace_once(
        path,
        "- A pending/reserved invocation interrupted by restart becomes `unknown`; an uncertain mutation becomes `unknown_side_effect`.\n",
        "- A pending/reserved invocation interrupted by restart becomes `unknown`; an uncertain mutation becomes `unknown_side_effect`.\n"
        "- Accepted task cancellation installs a durable invocation admission fence; pending work cancels, while reserved work requires proof of non-entry or settles conservatively.\n",
        label="docs durability cancellation boundary",
    )
    replace_once(
        path,
        "- Retry is not enabled by the durable invocation schema; a future retry requires a new identity and explicit budget.\n",
        "- Automatic retry remains disabled; an explicit child identity requires a terminal same-task parent, the exact next attempt and a separately authorized budget.\n",
        label="docs retry clarification",
    )


def patch_phase15_docs() -> None:
    replace_once(
        "docs/GOVERNED_GITHUB_READ_TOOLS.md",
        "Status: Phase 1.5 implementation in PR #52. The production boundary is read-only and fake/local in ordinary CI.\n",
        "Status: Phase 1.5 merged through PR #52. The production boundary remains read-only and fake/local in ordinary CI; live validation is a later staging step.\n",
        label="GitHub read document status",
    )
    replace_once(
        "docs/adr/0018-governed-read-tool-authority.md",
        "- Status: Accepted by Phase 1.5 implementation; merge evidence pending PR #52 final gate\n",
        "- Status: Accepted; merged through PR #52\n",
        label="ADR 0018 status",
    )


def patch_start_record() -> None:
    replace_once(
        "docs/validation/phase-1-6-cancellation-start.md",
        "# Phase 1.6 cancellation propagation — start record\n",
        "# Phase 1.6 cancellation propagation — start record\n\n"
        "Status: implementation completed in PR #54 candidate; superseded for acceptance evidence by [`phase-1-6-cancellation-propagation.md`](phase-1-6-cancellation-propagation.md).\n",
        label="Phase 1.6 start record status",
    )


def main() -> None:
    patch_master_plan()
    patch_agent_runtime()
    patch_docs_index()
    patch_phase15_docs()
    patch_start_record()


if __name__ == "__main__":
    main()
