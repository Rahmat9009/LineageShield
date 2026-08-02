from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LineageShield"
    context_provider: str = "demo"
    datahub_gms_url: str = "http://localhost:8080"
    datahub_gms_token: str = ""
    datahub_mutations_enabled: bool = False
    datahub_health_timeout_seconds: float = Field(default=6.0, gt=0, le=60)
    datahub_lineage_timeout_seconds: float = Field(default=30.0, gt=0, le=120)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
