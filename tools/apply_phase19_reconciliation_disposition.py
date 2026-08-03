from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"expected one exact anchor in {path}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def append_once(path: str, marker: str, content: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if marker in text:
        raise RuntimeError(f"candidate marker already exists in {path}")
    target.write_text(text.rstrip() + "\n\n" + content.strip() + "\n", encoding="utf-8")


contracts = "services/core/src/simorgh_core/agents/live_provider_staging_contracts.py"
service = "services/core/src/simorgh_core/agents/live_provider_staging.py"
tests = "services/core/tests/test_live_provider_staging.py"
validation = "docs/validation/phase-1-9-user-api-contract-candidate.md"

replace_once(
    contracts,
    "from decimal import Decimal\n",
    "from collections.abc import Sequence\nfrom decimal import Decimal\n",
)
replace_once(
    contracts,
    '''class LiveProviderStagingDisposition(StrEnum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"


class LiveProviderReconciliationCode(StrEnum):
''',
    '''class LiveProviderStagingDisposition(StrEnum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"


class LiveProviderReconciliationDisposition(StrEnum):
    EXACT = "exact"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"
    MISMATCH = "mismatch"


class LiveProviderReconciliationCode(StrEnum):
''',
)
replace_once(
    contracts,
    '''    TRANSACTION_LOOKUP_UNAVAILABLE = "transaction_lookup_unavailable"
    TRANSACTION_PENDING = "transaction_pending"
    TRANSACTION_MODEL_MISMATCH = "transaction_model_mismatch"
''',
    '''    TRANSACTION_LOOKUP_UNAVAILABLE = "transaction_lookup_unavailable"
    TRANSACTION_PENDING = "transaction_pending"
    TRANSACTION_REQUEST_MISMATCH = "transaction_request_mismatch"
    TRANSACTION_MODEL_MISMATCH = "transaction_model_mismatch"
''',
)
replace_once(
    contracts,
    '''    transaction: AvalAITransactionSummary | None = None
    reconciliation_codes: tuple[LiveProviderReconciliationCode, ...] = Field(
''',
    '''    transaction: AvalAITransactionSummary | None = None
    reconciliation_disposition: LiveProviderReconciliationDisposition
    reconciliation_codes: tuple[LiveProviderReconciliationCode, ...] = Field(
''',
)
replace_once(
    contracts,
    '''    completed_at_ms: int = Field(ge=0)

    @field_validator("reconciliation_codes")
''',
    '''    completed_at_ms: int = Field(ge=0)

    @model_validator(mode="before")
    @classmethod
    def derive_reconciliation_disposition(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if "reconciliation_disposition" not in payload:
            payload["reconciliation_disposition"] = (
                live_provider_reconciliation_disposition_for(
                    transaction_present=payload.get("transaction") is not None,
                    codes=_reconciliation_codes_from_payload(
                        payload.get("reconciliation_codes", ())
                    ),
                ).value
            )
        return payload

    @field_validator("reconciliation_codes")
''',
)
replace_once(
    contracts,
    '''        elif not self.reconciliation_codes:
            raise ValueError("incomplete staging result requires a typed code")
        cancellation_recorded = (
''',
    '''        elif not self.reconciliation_codes:
            raise ValueError("incomplete staging result requires a typed code")
        expected_reconciliation_disposition = (
            live_provider_reconciliation_disposition_for(
                transaction_present=self.transaction is not None,
                codes=self.reconciliation_codes,
            )
        )
        if self.reconciliation_disposition != expected_reconciliation_disposition:
            raise ValueError(
                "staging reconciliation disposition does not match evidence"
            )
        cancellation_recorded = (
''',
)
replace_once(
    contracts,
    '''        if (
            self.transaction is not None
            and self.provider_request_id != self.transaction.transaction_id
        ):
            raise ValueError("staging transaction identity does not match provider request")
''',
    '''        request_mismatch_recorded = (
            LiveProviderReconciliationCode.TRANSACTION_REQUEST_MISMATCH
            in self.reconciliation_codes
        )
        transaction_identity_mismatch = (
            self.transaction is not None
            and self.provider_request_id != self.transaction.transaction_id
        )
        if request_mismatch_recorded != transaction_identity_mismatch:
            raise ValueError(
                "staging transaction request identity mismatch is not typed"
            )
''',
)
replace_once(
    contracts,
    '''def live_provider_staging_trace_id_for(request_id: UUID) -> UUID:
''',
    '''_RECONCILIATION_MISMATCH_CODES = frozenset(
    {
        LiveProviderReconciliationCode.OUTPUT_CONTRACT_INVALID,
        LiveProviderReconciliationCode.TRANSACTION_REQUEST_MISMATCH,
        LiveProviderReconciliationCode.TRANSACTION_MODEL_MISMATCH,
        LiveProviderReconciliationCode.TRANSACTION_PROVIDER_MISMATCH,
        LiveProviderReconciliationCode.TRANSACTION_STATUS_INVALID,
        LiveProviderReconciliationCode.TRANSACTION_STREAM_INVALID,
        LiveProviderReconciliationCode.TRANSACTION_USAGE_MISMATCH,
        LiveProviderReconciliationCode.TRANSACTION_COST_EXCEEDED,
    }
)
_RECONCILIATION_UNAVAILABLE_CODES = frozenset(
    {
        LiveProviderReconciliationCode.PROVIDER_INVOCATION_CANCELLED,
        LiveProviderReconciliationCode.PROVIDER_INVOCATION_FAILED,
        LiveProviderReconciliationCode.PROVIDER_INVOCATION_UNKNOWN,
        LiveProviderReconciliationCode.PROVIDER_REQUEST_ID_MISSING,
        LiveProviderReconciliationCode.PROVIDER_REQUEST_ID_INVALID,
        LiveProviderReconciliationCode.TRANSACTION_LOOKUP_UNAVAILABLE,
    }
)


def live_provider_reconciliation_disposition_for(
    *,
    transaction_present: bool,
    codes: Sequence[LiveProviderReconciliationCode],
) -> LiveProviderReconciliationDisposition:
    normalized_codes = tuple(codes)
    code_set = frozenset(normalized_codes)
    if len(code_set) != len(normalized_codes):
        raise ValueError("reconciliation disposition requires unique codes")
    classified_codes = (
        _RECONCILIATION_MISMATCH_CODES
        | _RECONCILIATION_UNAVAILABLE_CODES
        | {LiveProviderReconciliationCode.TRANSACTION_PENDING}
    )
    if not code_set.issubset(classified_codes):
        raise ValueError("reconciliation disposition has an unclassified code")
    if code_set & _RECONCILIATION_MISMATCH_CODES:
        return LiveProviderReconciliationDisposition.MISMATCH
    if transaction_present:
        if code_set:
            raise ValueError("exact transaction conflicts with reconciliation codes")
        return LiveProviderReconciliationDisposition.EXACT
    if code_set == {LiveProviderReconciliationCode.TRANSACTION_PENDING}:
        return LiveProviderReconciliationDisposition.PENDING
    if LiveProviderReconciliationCode.TRANSACTION_PENDING in code_set:
        raise ValueError("pending evidence conflicts with unavailable evidence")
    if code_set and code_set.issubset(_RECONCILIATION_UNAVAILABLE_CODES):
        return LiveProviderReconciliationDisposition.UNAVAILABLE
    raise ValueError("reconciliation disposition requires transaction evidence or code")


def _reconciliation_codes_from_payload(
    value: object,
) -> tuple[LiveProviderReconciliationCode, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("staging reconciliation codes must be a sequence")
    normalized: list[LiveProviderReconciliationCode] = []
    for item in value:
        if isinstance(item, LiveProviderReconciliationCode):
            normalized.append(item)
        elif isinstance(item, str):
            try:
                normalized.append(LiveProviderReconciliationCode(item))
            except ValueError:
                raise ValueError(
                    "staging reconciliation code is unsupported"
                ) from None
        else:
            raise ValueError("staging reconciliation code is invalid")
    return tuple(normalized)


def live_provider_staging_trace_id_for(request_id: UUID) -> UUID:
''',
)
replace_once(
    contracts,
    '''    payload = (
        value.model_dump(mode="json")
        if isinstance(value, LiveProviderStagingResult)
        else dict(value)
    )
    for field in (
''',
    '''    payload = (
        value.model_dump(mode="json")
        if isinstance(value, LiveProviderStagingResult)
        else dict(value)
    )
    if "reconciliation_disposition" not in payload:
        payload["reconciliation_disposition"] = (
            live_provider_reconciliation_disposition_for(
                transaction_present=payload.get("transaction") is not None,
                codes=_reconciliation_codes_from_payload(
                    payload.get("reconciliation_codes", ())
                ),
            ).value
        )
    for field in (
''',
)
replace_once(
    contracts,
    '''    "LiveProviderPreflight",
    "LiveProviderReconciliationCode",
    "LiveProviderStagingContractError",
''',
    '''    "LiveProviderPreflight",
    "LiveProviderReconciliationCode",
    "LiveProviderReconciliationDisposition",
    "LiveProviderStagingContractError",
''',
)
replace_once(
    contracts,
    '''    "LiveProviderStagingResult",
    "live_provider_staging_result_id_for",
''',
    '''    "LiveProviderStagingResult",
    "live_provider_reconciliation_disposition_for",
    "live_provider_staging_result_id_for",
''',
)

replace_once(
    service,
    '''    LiveProviderReconciliationCode,
    LiveProviderStagingDisposition,
''',
    '''    LiveProviderReconciliationCode,
    LiveProviderStagingDisposition,
''',
)
replace_once(
    service,
    '''    live_provider_staging_result_id_for,
    live_provider_staging_result_sha256,
''',
    '''    live_provider_reconciliation_disposition_for,
    live_provider_staging_result_id_for,
    live_provider_staging_result_sha256,
''',
)
replace_once(
    service,
    '''                    _reconcile_transaction(
                        transaction=transaction,
                        gateway_result=gateway_result,
''',
    '''                    _reconcile_transaction(
                        transaction=transaction,
                        provider_request_id=provider_request_id,
                        gateway_result=gateway_result,
''',
)
replace_once(
    service,
    '''def _reconcile_transaction(
    *,
    transaction: AvalAITransactionSummary,
    gateway_result: BudgetedModelResult,
''',
    '''def _reconcile_transaction(
    *,
    transaction: AvalAITransactionSummary,
    provider_request_id: UUID,
    gateway_result: BudgetedModelResult,
''',
)
replace_once(
    service,
    '''    codes: set[LiveProviderReconciliationCode],
) -> None:
    if transaction.model != pricing.model_id:
''',
    '''    codes: set[LiveProviderReconciliationCode],
) -> None:
    if transaction.transaction_id != provider_request_id:
        codes.add(LiveProviderReconciliationCode.TRANSACTION_REQUEST_MISMATCH)
    if transaction.model != pricing.model_id:
''',
)
replace_once(
    service,
    '''        transaction=transaction,
        reconciliation_codes=codes,
        started_at_ms=started_at_ms,
''',
    '''        transaction=transaction,
        reconciliation_disposition=(
            live_provider_reconciliation_disposition_for(
                transaction_present=transaction is not None,
                codes=codes,
            )
        ),
        reconciliation_codes=codes,
        started_at_ms=started_at_ms,
''',
)

replace_once(
    tests,
    '''    LiveProviderReconciliationCode,
    LiveProviderStagingDisposition,
''',
    '''    LiveProviderReconciliationCode,
    LiveProviderReconciliationDisposition,
    LiveProviderStagingDisposition,
''',
)
replace_once(
    tests,
    '''    assert result.disposition == LiveProviderStagingDisposition.COMPLETED
    assert result.reconciliation_codes == ()
''',
    '''    assert result.disposition == LiveProviderStagingDisposition.COMPLETED
    assert result.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.EXACT
    )
    assert result.reconciliation_codes == ()
''',
)
replace_once(
    tests,
    '''    assert pending.disposition == LiveProviderStagingDisposition.INCOMPLETE
    assert pending.reconciliation_codes == (
''',
    '''    assert pending.disposition == LiveProviderStagingDisposition.INCOMPLETE
    assert pending.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.PENDING
    )
    assert pending.reconciliation_codes == (
''',
)
replace_once(
    tests,
    '''    unavailable = await failing_service.run(_request())
    assert unavailable.reconciliation_codes == (
''',
    '''    unavailable = await failing_service.run(_request())
    assert unavailable.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.UNAVAILABLE
    )
    assert unavailable.reconciliation_codes == (
''',
)
replace_once(
    tests,
    '''    assert result.disposition == LiveProviderStagingDisposition.INCOMPLETE
    assert result.reconciliation_codes == (
        LiveProviderReconciliationCode.TRANSACTION_COST_EXCEEDED,
''',
    '''    assert result.disposition == LiveProviderStagingDisposition.INCOMPLETE
    assert result.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.MISMATCH
    )
    assert result.reconciliation_codes == (
        LiveProviderReconciliationCode.TRANSACTION_COST_EXCEEDED,
''',
)
replace_once(
    tests,
    '''    assert result.disposition == LiveProviderStagingDisposition.INCOMPLETE
    assert result.reconciliation_codes == (
        LiveProviderReconciliationCode.PROVIDER_INVOCATION_UNKNOWN,
''',
    '''    assert result.disposition == LiveProviderStagingDisposition.INCOMPLETE
    assert result.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.UNAVAILABLE
    )
    assert result.reconciliation_codes == (
        LiveProviderReconciliationCode.PROVIDER_INVOCATION_UNKNOWN,
''',
)

append_once(
    validation,
    "## Canonical reconciliation disposition",
    '''## Canonical reconciliation disposition

Every sanitized staging result now carries one typed canonical projection:

```text
exact
pending
unavailable
mismatch
```

The projection is derived only from retained transaction presence and the
canonical detailed reconciliation-code tuple. `exact` requires a retained exact
transaction and no code. `pending` requires only bounded transaction-pending
evidence. `unavailable` covers provider cancellation/failure/uncertainty,
missing or invalid provider request identity and unavailable User API lookup.
`mismatch` has precedence when output, request, model, provider, status, stream,
usage or cost evidence conflicts.

The projection is included in the staging result canonical SHA-256. A caller may
omit the derived field while constructing an internal candidate, but supplying a
changed value fails typed validation. Transaction request-identity mismatch is
now a detailed typed code rather than an unstructured validation failure.
SQLite restart/replay retains the projection, and a rehashed payload whose
projection disagrees with its detailed evidence is rejected as corruption.
This increment changes no provider-call, polling, retry, cancellation, Trace,
credential or live-workflow behavior.''',
)

print("Phase 1.9 reconciliation disposition candidate applied.")
