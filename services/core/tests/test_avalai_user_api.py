from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from simorgh_core.providers.avalai_user_api import (
    AvalAICostSource,
    AvalAICreditSummary,
    AvalAIExactCost,
    AvalAITokenUsage,
    AvalAITransactionSummary,
    AvalAIUserAPIError,
    AvalAIUserAPIErrorCode,
    FakeAvalAIUserAPI,
    HttpAvalAIUserAPI,
)

_TRANSACTION_ID = UUID("019ac4a0-a8f4-7041-845f-3ea8f15dcf1a")
_SECRET = "private-api-key-marker-do-not-log"
_PRIVATE_MARKERS = (
    "192.0.2.25",
    "...ABCD",
    "private-safety-id",
    "private-tool-payload",
)


def _credit_payload() -> dict[str, object]:
    return {
        "limit": 0.0,
        "remaining_irt": 742927.85,
        "remaining_unit": 6.44622863340564,
        "total_unit": 6.44622863340564,
        "exchange_rate": 115250,
        "account_tier": 5,
        "credit_sources": {
            "grants": [{"description": "private-credit-source-marker"}],
            "packages": [],
        },
    }


def _transaction_payload() -> dict[str, object]:
    return {
        "id": str(_TRANSACTION_ID),
        "created_at": "2026-07-30T02:00:20.000Z",
        "requested_at": "2026-07-30T02:00:10.000Z",
        "safety_identifier": _PRIVATE_MARKERS[2],
        "model": "gpt-5.4-mini",
        "provider": "openai",
        "status_code": 200,
        "stream": False,
        "tokens": {
            "total": 30,
            "prompt": 10,
            "completion": 20,
            "reasoning": 0,
            "cached": 0,
            "prompt_details": {"private": "discarded"},
            "completion_details": {"private": "discarded"},
        },
        "ip_address": _PRIVATE_MARKERS[0],
        "tools": {"private": _PRIVATE_MARKERS[3]},
        "api_key_suffix": _PRIVATE_MARKERS[1],
        "cost": {
            "unit": "0.00001350",
            "paid_unit": "0.00001350",
            "paid_irt": "0.00",
            "paid_grant_irt": "1.55",
            "source": "credit_package",
            "currency": "UNIT",
        },
        "grants": [{"private": "discarded"}],
        "packages": [{"private": "discarded"}],
    }


def _lookup_payload(*, found: bool = True) -> dict[str, object]:
    return {
        "transactions": [_transaction_payload()] if found else [],
        "summary": {
            "requested": 1,
            "found": 1 if found else 0,
            "not_found_ids": [] if found else [str(_TRANSACTION_ID)],
        },
    }


def _headers() -> dict[str, str]:
    return {
        "x-ratelimit-limit-requests": "50",
        "x-ratelimit-remaining-requests": "49",
        "x-ratelimit-reset-requests": "12",
    }


@pytest.mark.asyncio
async def test_http_user_api_uses_only_fixed_endpoints_and_discards_private_data() -> None:
    requests: list[tuple[str, str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == f"Bearer {_SECRET}"
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, str(request.url), body))
        if request.url.path.endswith("/credit"):
            return httpx.Response(200, json=_credit_payload(), headers=_headers())
        return httpx.Response(200, json=_lookup_payload(), headers=_headers())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = HttpAvalAIUserAPI(api_key=SecretStr(_SECRET), client=client)
        credit = await api.get_credit()
        lookup = await api.lookup_transaction(_TRANSACTION_ID)

    assert requests == [
        ("GET", "https://api.avalai.ir/user/v1/credit", None),
        (
            "POST",
            "https://api.avalai.ir/user/v1/transactions/lookup",
            {"transaction_ids": [str(_TRANSACTION_ID)]},
        ),
    ]
    assert credit.remaining_unit == Decimal("6.44622863340564")
    assert credit.rate_limit.remaining_requests == 49
    assert credit.rate_limit.reset_after_ms == 12_000
    assert lookup.found and lookup.transaction is not None
    assert lookup.transaction.cost.unit == Decimal("0.00001350")
    serialized = json.dumps(
        {
            "credit": credit.model_dump(mode="json"),
            "lookup": lookup.model_dump(mode="json"),
        },
        sort_keys=True,
    )
    assert _SECRET not in serialized
    assert "private-credit-source-marker" not in serialized
    for marker in _PRIVATE_MARKERS:
        assert marker not in serialized


@pytest.mark.asyncio
async def test_lookup_not_found_is_typed_pending_state() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_lookup_payload(found=False))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = HttpAvalAIUserAPI(api_key=SecretStr(_SECRET), client=client)
        lookup = await api.lookup_transaction(_TRANSACTION_ID)

    assert lookup.found is False
    assert lookup.transaction is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    (
        (400, AvalAIUserAPIErrorCode.BAD_REQUEST),
        (401, AvalAIUserAPIErrorCode.UNAUTHORIZED),
        (403, AvalAIUserAPIErrorCode.FORBIDDEN),
        (404, AvalAIUserAPIErrorCode.NOT_FOUND),
        (429, AvalAIUserAPIErrorCode.RATE_LIMITED),
        (500, AvalAIUserAPIErrorCode.SERVER_ERROR),
    ),
)
async def test_http_status_failures_are_typed_and_redacted(
    status_code: int,
    expected_code: AvalAIUserAPIErrorCode,
) -> None:
    private_body = {"message": f"do not expose {_SECRET}"}

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json=private_body,
            headers={"x-ratelimit-reset-requests": "7"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = HttpAvalAIUserAPI(api_key=SecretStr(_SECRET), client=client)
        with pytest.raises(AvalAIUserAPIError) as captured:
            await api.get_credit()

    assert captured.value.code == expected_code
    assert _SECRET not in str(captured.value)
    assert captured.value.retry_after_ms == 7_000


@pytest.mark.asyncio
async def test_response_limit_and_unknown_fields_fail_closed_without_echo() -> None:
    responses = [
        httpx.Response(200, content=b"x" * 2_000),
        httpx.Response(
            200,
            json={**_credit_payload(), "unexpected": f"private {_SECRET}"},
        ),
    ]

    async def handler(_: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = HttpAvalAIUserAPI(
            api_key=SecretStr(_SECRET),
            client=client,
            max_response_bytes=1_024,
        )
        with pytest.raises(AvalAIUserAPIError) as too_large:
            await api.get_credit()
        with pytest.raises(AvalAIUserAPIError) as invalid:
            await api.get_credit()

    assert too_large.value.code == AvalAIUserAPIErrorCode.RESPONSE_TOO_LARGE
    assert invalid.value.code == AvalAIUserAPIErrorCode.INVALID_RESPONSE
    assert _SECRET not in str(invalid.value)


def test_user_api_rejects_unreviewed_base_url_and_non_v7_identity() -> None:
    with pytest.raises(ValueError, match="outside reviewed allowlist"):
        HttpAvalAIUserAPI(
            api_key=SecretStr(_SECRET),
            base_url="https://example.invalid/user/v1",
        )

    with pytest.raises(ValidationError, match="UUIDv7"):
        AvalAITransactionSummary(
            transaction_id=UUID("00000000-0000-4000-8000-000000000000"),
            created_at="2026-07-30T02:00:20Z",
            requested_at="2026-07-30T02:00:10Z",
            model="gpt-5.4-mini",
            provider="openai",
            status_code=200,
            stream=False,
            tokens=AvalAITokenUsage(
                total=1,
                prompt=1,
                completion=0,
                reasoning=0,
                cached=0,
            ),
            cost=AvalAIExactCost(
                unit=Decimal("0"),
                paid_unit=Decimal("0"),
                paid_irt=Decimal("0"),
                paid_grant_irt=Decimal("0"),
                source=AvalAICostSource.CREDIT,
                currency="UNIT",
            ),
        )


@pytest.mark.asyncio
async def test_fake_user_api_is_deterministic_and_zero_network() -> None:
    credit = AvalAICreditSummary(
        limit_irt=Decimal("0"),
        remaining_irt=Decimal("1000"),
        remaining_unit=Decimal("1"),
        total_unit=Decimal("1"),
        exchange_rate_irt_per_unit=1000,
        account_tier=1,
    )
    transaction = AvalAITransactionSummary(
        transaction_id=_TRANSACTION_ID,
        created_at="2026-07-30T02:00:20Z",
        requested_at="2026-07-30T02:00:10Z",
        model="gpt-5.4-mini",
        provider="openai",
        status_code=200,
        stream=False,
        tokens=AvalAITokenUsage(
            total=3,
            prompt=2,
            completion=1,
            reasoning=0,
            cached=0,
        ),
        cost=AvalAIExactCost(
            unit=Decimal("0.000001"),
            paid_unit=Decimal("0.000001"),
            paid_irt=Decimal("0"),
            paid_grant_irt=Decimal("0"),
            source=AvalAICostSource.CREDIT,
            currency="UNIT",
        ),
    )
    api = FakeAvalAIUserAPI(
        credit=credit,
        transactions={_TRANSACTION_ID: transaction},
    )

    assert await api.get_credit() == credit
    found = await api.lookup_transaction(_TRANSACTION_ID)
    missing = await api.lookup_transaction(
        UUID("019ac4a0-a8f4-7041-845f-3ea8f15dcf1b")
    )

    assert found.transaction == transaction
    assert missing.found is False
    assert api.credit_calls == 1
    assert api.lookup_calls == 2
