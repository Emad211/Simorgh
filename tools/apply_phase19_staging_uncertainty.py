from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one anchor in {path}, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def append_once(path: str, marker: str, content: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if marker in text:
        raise RuntimeError(f"marker already exists in {path}")
    target.write_text(text.rstrip() + "\n\n" + content.strip() + "\n", encoding="utf-8")


replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging_contracts.py",
    "    PROVIDER_INVOCATION_FAILED = \"provider_invocation_failed\"\n"
    "    PROVIDER_INVOCATION_UNKNOWN = \"provider_invocation_unknown\"\n",
    "    PROVIDER_INVOCATION_CANCELLED = \"provider_invocation_cancelled\"\n"
    "    PROVIDER_INVOCATION_FAILED = \"provider_invocation_failed\"\n"
    "    PROVIDER_INVOCATION_UNKNOWN = \"provider_invocation_unknown\"\n",
)
replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging_contracts.py",
    "        elif not self.reconciliation_codes:\n"
    "            raise ValueError(\"incomplete staging result requires a typed code\")\n"
    "        if self.provider_request_id is not None and self.provider_request_id.version != 7:\n",
    "        elif not self.reconciliation_codes:\n"
    "            raise ValueError(\"incomplete staging result requires a typed code\")\n"
    "        cancellation_recorded = (\n"
    "            LiveProviderReconciliationCode.PROVIDER_INVOCATION_CANCELLED\n"
    "            in self.reconciliation_codes\n"
    "        )\n"
    "        uncertainty_recorded = (\n"
    "            LiveProviderReconciliationCode.PROVIDER_INVOCATION_UNKNOWN\n"
    "            in self.reconciliation_codes\n"
    "        )\n"
    "        if self.invocation_state == InvocationState.CANCELLED:\n"
    "            if not cancellation_recorded:\n"
    "                raise ValueError(\n"
    "                    \"cancelled staging result requires cancellation code\"\n"
    "                )\n"
    "            if self.committed_usage != UsageVector():\n"
    "                raise ValueError(\n"
    "                    \"cancelled-before-entry staging result requires zero usage\"\n"
    "                )\n"
    "        if cancellation_recorded and self.invocation_state not in {\n"
    "            InvocationState.CANCELLED,\n"
    "            InvocationState.COMPLETED,\n"
    "            InvocationState.UNKNOWN,\n"
    "        }:\n"
    "            raise ValueError(\n"
    "                \"staging cancellation code conflicts with invocation state\"\n"
    "            )\n"
    "        if self.invocation_state == InvocationState.UNKNOWN and not uncertainty_recorded:\n"
    "            raise ValueError(\n"
    "                \"unknown staging invocation requires uncertainty code\"\n"
    "            )\n"
    "        if uncertainty_recorded and self.invocation_state != InvocationState.UNKNOWN:\n"
    "            raise ValueError(\n"
    "                \"staging uncertainty code conflicts with invocation state\"\n"
    "            )\n"
    "        if self.provider_request_id is not None and self.provider_request_id.version != 7:\n",
)

replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging.py",
    "        gateway_result: BudgetedModelResult | None = None\n"
    "        gateway_failed = False\n",
    "        gateway_result: BudgetedModelResult | None = None\n"
    "        gateway_failed = False\n"
    "        gateway_cancelled: asyncio.CancelledError | None = None\n",
)
replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging.py",
    "        except asyncio.CancelledError:\n"
    "            raise\n"
    "        except (BudgetError, ModelGatewayError):\n"
    "            gateway_failed = True\n",
    "        except asyncio.CancelledError as exc:\n"
    "            gateway_cancelled = exc\n"
    "        except (BudgetError, ModelGatewayError):\n"
    "            gateway_failed = True\n",
)
replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging.py",
    "        invocation = self._require_invocation(request.invocation_id)\n"
    "        codes: set[LiveProviderReconciliationCode] = set()\n"
    "        provider_request_id: UUID | None = None\n"
    "        output_sha256: str | None = None\n"
    "        output_characters: int | None = None\n"
    "        transaction: AvalAITransactionSummary | None = None\n\n"
    "        if gateway_failed:\n"
    "            if invocation.state in {\n"
    "                InvocationState.UNKNOWN,\n"
    "                InvocationState.UNKNOWN_SIDE_EFFECT,\n"
    "            }:\n"
    "                codes.add(\n"
    "                    LiveProviderReconciliationCode.PROVIDER_INVOCATION_UNKNOWN\n"
    "                )\n"
    "            else:\n"
    "                codes.add(\n"
    "                    LiveProviderReconciliationCode.PROVIDER_INVOCATION_FAILED\n"
    "                )\n",
    "        invocation = self._require_invocation(request.invocation_id)\n"
    "        if not invocation.terminal:\n"
    "            raise LiveProviderStagingExecutionError(\n"
    "                \"staging invocation did not reach durable terminal state\"\n"
    "            )\n"
    "        codes: set[LiveProviderReconciliationCode] = set()\n"
    "        provider_request_id: UUID | None = None\n"
    "        output_sha256: str | None = None\n"
    "        output_characters: int | None = None\n"
    "        transaction: AvalAITransactionSummary | None = None\n\n"
    "        if gateway_cancelled is not None:\n"
    "            codes.add(\n"
    "                LiveProviderReconciliationCode.PROVIDER_INVOCATION_CANCELLED\n"
    "            )\n"
    "            if invocation.state == InvocationState.UNKNOWN:\n"
    "                codes.add(\n"
    "                    LiveProviderReconciliationCode.PROVIDER_INVOCATION_UNKNOWN\n"
    "                )\n"
    "            elif invocation.state != InvocationState.CANCELLED:\n"
    "                raise LiveProviderStagingExecutionError(\n"
    "                    \"cancelled staging invocation has inconsistent terminal state\"\n"
    "                )\n"
    "        elif gateway_failed:\n"
    "            if invocation.state == InvocationState.CANCELLED:\n"
    "                codes.add(\n"
    "                    LiveProviderReconciliationCode.PROVIDER_INVOCATION_CANCELLED\n"
    "                )\n"
    "            elif invocation.state == InvocationState.UNKNOWN:\n"
    "                codes.add(\n"
    "                    LiveProviderReconciliationCode.PROVIDER_INVOCATION_UNKNOWN\n"
    "                )\n"
    "            elif invocation.state == InvocationState.UNKNOWN_SIDE_EFFECT:\n"
    "                raise LiveProviderStagingExecutionError(\n"
    "                    \"model staging invocation cannot be unknown-side-effect\"\n"
    "                )\n"
    "            else:\n"
    "                codes.add(\n"
    "                    LiveProviderReconciliationCode.PROVIDER_INVOCATION_FAILED\n"
    "                )\n",
)
replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging.py",
    "            if provider_request_id is not None:\n"
    "                transaction = await self._lookup_transaction(\n"
    "                    provider_request_id,\n"
    "                    codes=codes,\n"
    "                )\n"
    "                if transaction is not None:\n",
    "            if provider_request_id is not None:\n"
    "                try:\n"
    "                    transaction = await self._lookup_transaction(\n"
    "                        provider_request_id,\n"
    "                        codes=codes,\n"
    "                    )\n"
    "                except asyncio.CancelledError as exc:\n"
    "                    gateway_cancelled = exc\n"
    "                    codes.add(\n"
    "                        LiveProviderReconciliationCode.PROVIDER_INVOCATION_CANCELLED\n"
    "                    )\n"
    "                if transaction is not None:\n",
)
replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging.py",
    "        claim = self._results.claim(record)\n"
    "        return claim.record.model_copy(\n"
    "            update={\n"
    "                \"replayed\": claim.kind == LiveProviderStagingClaimKind.REPLAY,\n"
    "            }\n"
    "        )\n",
    "        claim = self._results.claim(record)\n"
    "        persisted = claim.record.model_copy(\n"
    "            update={\n"
    "                \"replayed\": claim.kind == LiveProviderStagingClaimKind.REPLAY,\n"
    "            }\n"
    "        )\n"
    "        if gateway_cancelled is not None:\n"
    "            raise gateway_cancelled from None\n"
    "        return persisted\n",
)

append_once(
    "docs/validation/phase-1-9-user-api-contract-candidate.md",
    "## Durable cancellation and provider-transport uncertainty",
    r'''
## Durable cancellation and provider-transport uncertainty

The staging service now persists a sanitized immutable incomplete result for
terminal cancellation and provider transport uncertainty rather than losing the
staging audit record.

The preserved state matrix is:

```text
reserved invocation with typed proof of non-entry
  -> invocation cancelled
  -> zero committed usage
  -> provider_invocation_cancelled
  -> zero external provider entry

cancellation while the provider request may have entered
  -> invocation unknown
  -> conservative reserved usage committed once
  -> provider_invocation_cancelled + provider_invocation_unknown
  -> result persisted before cancellation is re-raised

provider transport exception after reservation
  -> invocation unknown
  -> conservative reserved usage committed once
  -> provider_invocation_unknown
  -> no retry

cancellation during transaction lookup after provider completion
  -> invocation remains completed
  -> provider request/output fingerprints retained
  -> provider_invocation_cancelled
  -> no second model request
```

Exact staging replay still checks the durable result before credit, model
catalog, provider or User API entry. SQLite close/reopen replay therefore adds no
model call, User API call or usage. Cancellation and transport exception text,
prompt/output text, headers, credentials and raw provider/User API bodies remain
excluded from the stored result.

Focused acceptance covers a successful canary, cancellation before external
provider entry, cancellation after possible provider entry, cancellation during
transaction lookup, transport uncertainty, SQLite restart and exact zero-external
replay. The transfer gate runs Ruff, strict MyPy and the complete Core suite
before product publication; ordinary exact-head CI must additionally pass the
unchanged Android build, JVM tests, lint and Debug APK upload.
''',
)

print("Phase 1.9 staging uncertainty candidate applied.")
