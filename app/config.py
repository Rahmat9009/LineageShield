from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LineageShield"
    context_provider: str = "demo"
    datahub_gms_url: str = "http://localhost:8080"
    datahub_gms_token: str = ""
    datahub_mutations_enabled: bool = False
    datahub_mutation_timeout_seconds: float = Field(default=12.0, gt=0, le=60)
    analysis_store_ttl_seconds: int = Field(default=1_800, ge=60, le=86_400)
    analysis_store_max_entries: int = Field(default=100, ge=1, le=1_000)
    datahub_health_timeout_seconds: float = Field(default=6.0, gt=0, le=60)
    datahub_lineage_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    datahub_enrichment_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    datahub_enrichment_request_timeout_seconds: float = Field(
        default=6.0,
        gt=0,
        le=60,
    )
    datahub_enrichment_concurrency: int = Field(default=4, ge=1, le=12)
    datahub_enrichment_batch_size: int = Field(default=50, ge=1, le=100)
    agent_context_timeout_seconds: float = Field(default=24.0, gt=0, le=60)
    agent_context_tool_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    agent_context_max_lineage_results: int = Field(default=60, ge=1, le=100)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
