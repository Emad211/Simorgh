from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
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

    avalai_api_key: SecretStr | None = None
    avalai_base_url: str = "https://api.avalai.ir/v1"
    avalai_user_api_base_url: str = "https://api.avalai.ir/user/v1"
    avalai_default_model: str = "gpt-5.4-mini"

    @property
    def has_model_credentials(self) -> bool:
        return bool(self.avalai_api_key and self.avalai_api_key.get_secret_value())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
