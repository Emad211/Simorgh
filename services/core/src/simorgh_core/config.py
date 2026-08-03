from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    simorgh_env: Literal["development", "test", "production"] = "development"
    simorgh_log_level: str = "INFO"
    simorgh_host: str = "127.0.0.1"
    simorgh_port: int = 8080
    simorgh_device_token: SecretStr | None = None
    simorgh_operator_token: SecretStr | None = None
    simorgh_action_journal_path: str = Field(
        default=".simorgh/action-journal.sqlite3",
        min_length=1,
        max_length=4_096,
    )
    simorgh_action_journal_max_terminal_records: int = Field(
        default=256,
        ge=1,
        le=100_000,
    )
    simorgh_agent_task_store_path: str = Field(
        default=".simorgh/agent-tasks.sqlite3",
        min_length=1,
        max_length=4_096,
    )
    simorgh_agent_task_store_max_terminal_records: int = Field(
        default=10_000,
        ge=1,
        le=1_000_000,
    )
    simorgh_invocation_store_path: str = Field(
        default=".simorgh/invocations.sqlite3",
        min_length=1,
        max_length=4_096,
    )
    simorgh_result_store_path: str = Field(
        default=".simorgh/results.sqlite3",
        min_length=1,
        max_length=4_096,
    )
    simorgh_context_store_path: str = Field(
        default=".simorgh/contexts.sqlite3",
        min_length=1,
        max_length=4_096,
    )
    simorgh_context_store_max_terminal_records: int = Field(
        default=10_000,
        ge=0,
        le=1_000_000,
    )
    simorgh_trace_store_path: str = Field(
        default=".simorgh/traces.sqlite3",
        min_length=1,
        max_length=4_096,
    )
    simorgh_trace_store_max_terminal_records: int = Field(
        default=10_000,
        ge=0,
        le=1_000_000,
    )
    simorgh_live_provider_staging_result_store_path: str = Field(
        default=".simorgh/live-provider-staging-results.sqlite3",
        min_length=1,
        max_length=4_096,
    )

    avalai_api_key: SecretStr | None = None
    avalai_base_url: str = "https://api.avalai.ir/v1"
    avalai_user_api_base_url: str = "https://api.avalai.ir/user/v1"
    avalai_default_model: str = "gpt-5.4-mini"

    @property
    def has_model_credentials(self) -> bool:
        return bool(self.avalai_api_key and self.avalai_api_key.get_secret_value())

    @property
    def has_device_gateway_credentials(self) -> bool:
        return bool(self.simorgh_device_token and self.simorgh_device_token.get_secret_value())

    @property
    def has_operator_credentials(self) -> bool:
        return bool(self.simorgh_operator_token and self.simorgh_operator_token.get_secret_value())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
