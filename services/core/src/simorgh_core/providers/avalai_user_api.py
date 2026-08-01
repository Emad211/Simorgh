from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Literal, NoReturn, Protocol, Self
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from simorgh_core.agents.live_provider_staging_contracts import (
    AVALAI_USER_API_BASE_URL,
)

_DECIMAL_PATTERN = r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,15})?$"
_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$"
_TRANSACTION_REQUIRED_KEYS = frozenset(
    {
        "id",
        "created_at",
        "requested_at",
        "safety_identifier",
        "model",
        "provider",
        "status_code",
        "stream",
        "tokens",
        "ip_address",
        "tools",
        "api_key_suffix",
        "cost",
        "grants",
        "packages",
    }
)
_TOKEN_REQUIRED_KEYS = frozenset(
    {
        "total",
        "prompt",
        "completion",
        "reasoning",
        "cached",
        "prompt_details",
        "completion_details",
    }
)
_COST_REQUIRED_KEYS = frozenset(
    {
        "unit",
        "paid_unit",
        "paid_irt",
        "paid_grant_irt",
        "source",
        "currency",
    }
)


class AvalAIUserAPIErrorCode(StrEnum):
    BAD_REQUEST = "bad_request"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    TRANSPORT_ERROR = "transport_error"
    RESPONSE_TOO_LARGE = "response_too_large"
    INVALID_RESPONSE = "invalid_response"


class AvalAIUserAPIError(RuntimeError):
    """Sanitized User API failure that never carries response or credential data."""

    def __init__(
        self,
        code: AvalAIUserAPIErrorCode,
        *,
        retry_after_ms: int | None = None,
    ) -> None:
        super().__init__(f"AvalAI User API request failed: {code.value}")
        self.code = code
        self.retry_after_ms = retry_after_ms


class AvalAIRateLimitSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    limit_requests: int | None = Field(default=None, ge=0, le=1_000_000)
    remaining_requests: int | None = Field(default=None, ge=0, le=1_000_000)
    reset_after_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class AvalAICreditSummary(BaseModel):
    """Safe credit projection; grant/package bodies are intentionally discarded."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    limit_irt: Decimal = Field(ge=0, max_digits=30, decimal_places=15)
    remaining_irt: Decimal = Field(ge=0, max_digits=30, decimal_places=15)
    remaining_unit: Decimal = Field(ge=0, max_digits=30, decimal_places=15)
    total_unit: Decimal = Field(ge=0, max_digits=30, decimal_places=15)
    exchange_rate_irt_per_unit: int = Field(ge=0, le=10**12)
    account_tier: int = Field(ge=0, le=5)
    unit_currency: Literal["UNIT"] = "UNIT"
    local_currency: Literal["IRT"] = "IRT"
    rate_limit: AvalAIRateLimitSummary = Field(default_factory=AvalAIRateLimitSummary)


class AvalAITokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    total: int = Field(ge=0, le=10**9)
    prompt: int = Field(ge=0, le=10**9)
    completion: int = Field(ge=0, le=10**9)
    reasoning: int = Field(ge=0, le=10**9)
    cached: int = Field(ge=0, le=10**9)

    @model_validator(mode="after")
    def validate_usage(self) -> Self:
        if self.total < self.prompt or self.total < self.completion:
            raise ValueError("transaction total tokens are inconsistent")
        return self


class AvalAICostSource(StrEnum):
    CREDIT = "credit"
    CREDIT_PACKAGE = "credit_package"
    GRANT = "grant"
    BALANCE = "balance"


class AvalAIExactCost(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    unit: Decimal = Field(ge=0, max_digits=30, decimal_places=15)
    paid_unit: Decimal = Field(ge=0, max_digits=30, decimal_places=15)
    paid_irt: Decimal = Field(ge=0, max_digits=30, decimal_places=15)
    paid_grant_irt: Decimal = Field(ge=0, max_digits=30, decimal_places=15)
    source: AvalAICostSource
    currency: Literal["UNIT"]

    @model_validator(mode="after")
    def validate_cost(self) -> Self:
        if self.paid_unit > self.unit:
            raise ValueError("paid unit cost cannot exceed total unit cost")
        return self


class AvalAITransactionSummary(BaseModel):
    """Sanitized transaction projection without IP, key suffix, tools or safety ID."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    transaction_id: UUID
    created_at: datetime
    requested_at: datetime
    model: str = Field(pattern=_IDENTIFIER_PATTERN, max_length=256)
    provider: str = Field(pattern=_IDENTIFIER_PATTERN, max_length=128)
    status_code: int = Field(ge=100, le=599)
    stream: bool
    tokens: AvalAITokenUsage
    cost: AvalAIExactCost

    @field_validator("transaction_id")
    @classmethod
    def validate_transaction_id(cls, value: UUID) -> UUID:
        if value.version != 7:
            raise ValueError("AvalAI transaction identity must be UUIDv7")
        return value

    @field_validator("created_at", "requested_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("AvalAI transaction timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_transaction(self) -> Self:
        if self.created_at < self.requested_at:
            raise ValueError("transaction processing time cannot precede request time")
        return self


class AvalAITransactionLookupResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    requested_transaction_id: UUID
    found: bool
    transaction: AvalAITransactionSummary | None = None
    rate_limit: AvalAIRateLimitSummary = Field(default_factory=AvalAIRateLimitSummary)

    @model_validator(mode="after")
    def validate_lookup(self) -> Self:
        if self.found != (self.transaction is not None):
            raise ValueError("transaction lookup found state is inconsistent")
        if self.transaction is not None:
            if self.transaction.transaction_id != self.requested_transaction_id:
                raise ValueError("transaction lookup returned another request identity")
        return self


class AvalAIUserAPI(Protocol):
    async def get_credit(self) -> AvalAICreditSummary: ...

    async def lookup_transaction(
        self,
        transaction_id: UUID,
    ) -> AvalAITransactionLookupResult: ...


class FakeAvalAIUserAPI:
    """Deterministic zero-network User API used by ordinary CI."""

    def __init__(
        self,
        *,
        credit: AvalAICreditSummary,
        transactions: Mapping[UUID, AvalAITransactionSummary] | None = None,
    ) -> None:
        self._credit = AvalAICreditSummary.model_validate(credit.model_dump(mode="json"))
        self._transactions = {
            key: AvalAITransactionSummary.model_validate(value.model_dump(mode="json"))
            for key, value in (transactions or {}).items()
        }
        self.credit_calls = 0
        self.lookup_calls = 0

    async def get_credit(self) -> AvalAICreditSummary:
        self.credit_calls += 1
        return AvalAICreditSummary.model_validate(self._credit.model_dump(mode="json"))

    async def lookup_transaction(
        self,
        transaction_id: UUID,
    ) -> AvalAITransactionLookupResult:
        self.lookup_calls += 1
        transaction = self._transactions.get(transaction_id)
        return AvalAITransactionLookupResult(
            requested_transaction_id=transaction_id,
            found=transaction is not None,
            transaction=transaction,
        )


class HttpAvalAIUserAPI:
    """Narrow AvalAI User API client with two fixed reviewed operations."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str = AVALAI_USER_API_BASE_URL,
        timeout_ms: int = 10_000,
        max_response_bytes: int = 256_000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if base_url != AVALAI_USER_API_BASE_URL:
            raise ValueError("AvalAI User API base URL is outside reviewed allowlist")
        if timeout_ms < 1_000 or timeout_ms > 30_000:
            raise ValueError("AvalAI User API timeout is outside reviewed limits")
        if max_response_bytes < 1_024 or max_response_bytes > 1_000_000:
            raise ValueError("AvalAI User API response limit is outside reviewed limits")
        secret = api_key.get_secret_value()
        if not secret:
            raise ValueError("AvalAI User API credential is required")
        self._api_key = secret
        self._base_url = base_url
        self._timeout = timeout_ms / 1_000
        self._max_response_bytes = max_response_bytes
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def get_credit(self) -> AvalAICreditSummary:
        payload, rate_limit = await self._request("GET", "/credit")
        return _parse_credit(payload, rate_limit=rate_limit)

    async def lookup_transaction(
        self,
        transaction_id: UUID,
    ) -> AvalAITransactionLookupResult:
        if transaction_id.version != 7:
            raise ValueError("AvalAI transaction identity must be UUIDv7")
        payload, rate_limit = await self._request(
            "POST",
            "/transactions/lookup",
            json_body={"transaction_ids": [str(transaction_id)]},
        )
        return _parse_lookup(
            payload,
            requested_transaction_id=transaction_id,
            rate_limit=rate_limit,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: Literal["GET", "POST"],
        path: Literal["/credit", "/transactions/lookup"],
        *,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], AvalAIRateLimitSummary]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                json=json_body,
                timeout=self._timeout,
            )
        except (httpx.TimeoutException, httpx.TransportError):
            raise AvalAIUserAPIError(AvalAIUserAPIErrorCode.TRANSPORT_ERROR) from None
        rate_limit = _parse_rate_limit_headers(response.headers)
        if len(response.content) > self._max_response_bytes:
            raise AvalAIUserAPIError(AvalAIUserAPIErrorCode.RESPONSE_TOO_LARGE)
        if response.status_code < 200 or response.status_code >= 300:
            raise AvalAIUserAPIError(
                _error_code_for_status(response.status_code),
                retry_after_ms=rate_limit.reset_after_ms,
            )
        try:
            decoded = json.loads(
                response.content,
                parse_float=Decimal,
                parse_int=int,
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise AvalAIUserAPIError(AvalAIUserAPIErrorCode.INVALID_RESPONSE) from None
        if not isinstance(decoded, dict):
            raise AvalAIUserAPIError(AvalAIUserAPIErrorCode.INVALID_RESPONSE)
        return decoded, rate_limit


def _parse_credit(
    payload: dict[str, Any],
    *,
    rate_limit: AvalAIRateLimitSummary,
) -> AvalAICreditSummary:
    _require_exact_keys(
        payload,
        required={
            "limit",
            "remaining_irt",
            "remaining_unit",
            "total_unit",
            "exchange_rate",
            "account_tier",
            "credit_sources",
        },
    )
    if not isinstance(payload["credit_sources"], dict):
        _invalid_response()
    try:
        return AvalAICreditSummary(
            limit_irt=_decimal(payload["limit"]),
            remaining_irt=_decimal(payload["remaining_irt"]),
            remaining_unit=_decimal(payload["remaining_unit"]),
            total_unit=_decimal(payload["total_unit"]),
            exchange_rate_irt_per_unit=payload["exchange_rate"],
            account_tier=payload["account_tier"],
            rate_limit=rate_limit,
        )
    except (TypeError, ValueError):
        _invalid_response()


def _parse_lookup(
    payload: dict[str, Any],
    *,
    requested_transaction_id: UUID,
    rate_limit: AvalAIRateLimitSummary,
) -> AvalAITransactionLookupResult:
    _require_exact_keys(payload, required={"transactions", "summary"})
    transactions = payload["transactions"]
    summary = payload["summary"]
    if not isinstance(transactions, list) or not isinstance(summary, dict):
        _invalid_response()
    _require_exact_keys(summary, required={"requested", "found", "not_found_ids"})
    if summary["requested"] != 1 or summary["found"] not in {0, 1}:
        _invalid_response()
    not_found_ids = summary["not_found_ids"]
    if not isinstance(not_found_ids, list) or len(not_found_ids) > 1:
        _invalid_response()
    if summary["found"] == 0:
        if transactions or not_found_ids != [str(requested_transaction_id)]:
            _invalid_response()
        return AvalAITransactionLookupResult(
            requested_transaction_id=requested_transaction_id,
            found=False,
            rate_limit=rate_limit,
        )
    if len(transactions) != 1 or not_found_ids:
        _invalid_response()
    transaction = _parse_transaction(transactions[0])
    try:
        return AvalAITransactionLookupResult(
            requested_transaction_id=requested_transaction_id,
            found=True,
            transaction=transaction,
            rate_limit=rate_limit,
        )
    except ValueError:
        _invalid_response()


def _parse_transaction(value: Any) -> AvalAITransactionSummary:
    if not isinstance(value, dict):
        _invalid_response()
    _require_exact_keys(value, required=_TRANSACTION_REQUIRED_KEYS)
    tokens = value["tokens"]
    cost = value["cost"]
    if not isinstance(tokens, dict) or not isinstance(cost, dict):
        _invalid_response()
    _require_exact_keys(tokens, required=_TOKEN_REQUIRED_KEYS)
    _require_exact_keys(cost, required=_COST_REQUIRED_KEYS)
    if not isinstance(tokens["prompt_details"], dict):
        _invalid_response()
    if not isinstance(tokens["completion_details"], dict):
        _invalid_response()
    if not isinstance(value["tools"], dict):
        _invalid_response()
    if not isinstance(value["grants"], list) or not isinstance(value["packages"], list):
        _invalid_response()
    try:
        return AvalAITransactionSummary(
            transaction_id=value["id"],
            created_at=value["created_at"],
            requested_at=value["requested_at"],
            model=value["model"],
            provider=value["provider"],
            status_code=value["status_code"],
            stream=value["stream"],
            tokens=AvalAITokenUsage(
                total=tokens["total"],
                prompt=tokens["prompt"],
                completion=tokens["completion"],
                reasoning=tokens["reasoning"],
                cached=tokens["cached"],
            ),
            cost=AvalAIExactCost(
                unit=_decimal(cost["unit"]),
                paid_unit=_decimal(cost["paid_unit"]),
                paid_irt=_decimal(cost["paid_irt"]),
                paid_grant_irt=_decimal(cost["paid_grant_irt"]),
                source=cost["source"],
                currency=cost["currency"],
            ),
        )
    except (TypeError, ValueError):
        _invalid_response()


def _parse_rate_limit_headers(headers: httpx.Headers) -> AvalAIRateLimitSummary:
    return AvalAIRateLimitSummary(
        limit_requests=_optional_header_int(headers, "x-ratelimit-limit-requests"),
        remaining_requests=_optional_header_int(
            headers,
            "x-ratelimit-remaining-requests",
        ),
        reset_after_ms=_optional_header_seconds_ms(
            headers,
            "x-ratelimit-reset-requests",
        ),
    )


def _optional_header_int(headers: httpx.Headers, name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        _invalid_response()
    if parsed < 0:
        _invalid_response()
    return parsed


def _optional_header_seconds_ms(headers: httpx.Headers, name: str) -> int | None:
    seconds = _optional_header_int(headers, name)
    return None if seconds is None else seconds * 1_000


def _error_code_for_status(status_code: int) -> AvalAIUserAPIErrorCode:
    if status_code == 400:
        return AvalAIUserAPIErrorCode.BAD_REQUEST
    if status_code == 401:
        return AvalAIUserAPIErrorCode.UNAUTHORIZED
    if status_code == 403:
        return AvalAIUserAPIErrorCode.FORBIDDEN
    if status_code == 404:
        return AvalAIUserAPIErrorCode.NOT_FOUND
    if status_code == 429:
        return AvalAIUserAPIErrorCode.RATE_LIMITED
    return AvalAIUserAPIErrorCode.SERVER_ERROR


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: set[str] | frozenset[str],
) -> None:
    if set(value) != set(required):
        _invalid_response()


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        _invalid_response()
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        _invalid_response()
    if not parsed.is_finite() or parsed < 0:
        _invalid_response()
    encoded = format(parsed, "f")
    if not re.fullmatch(_DECIMAL_PATTERN, encoded):
        _invalid_response()
    return parsed


def _invalid_response() -> NoReturn:
    raise AvalAIUserAPIError(AvalAIUserAPIErrorCode.INVALID_RESPONSE)


__all__ = [
    "AvalAICostSource",
    "AvalAICreditSummary",
    "AvalAIExactCost",
    "AvalAIRateLimitSummary",
    "AvalAITokenUsage",
    "AvalAITransactionLookupResult",
    "AvalAITransactionSummary",
    "AvalAIUserAPI",
    "AvalAIUserAPIError",
    "AvalAIUserAPIErrorCode",
    "FakeAvalAIUserAPI",
    "HttpAvalAIUserAPI",
]
