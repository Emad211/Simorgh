from typing import Literal

AVALAI_PROVIDER_ID: Literal["avalai"] = "avalai"
AVALAI_API_BASE_URL: Literal["https://api.avalai.ir/v1"] = (
    "https://api.avalai.ir/v1"
)
AVALAI_USER_API_BASE_URL: Literal["https://api.avalai.ir/user/v1"] = (
    "https://api.avalai.ir/user/v1"
)

__all__ = [
    "AVALAI_API_BASE_URL",
    "AVALAI_PROVIDER_ID",
    "AVALAI_USER_API_BASE_URL",
]
