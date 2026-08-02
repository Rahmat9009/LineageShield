from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


ChangeType = Literal["rename", "drop", "type_change", "add"]
Decision = Literal["ALLOW", "REVIEW", "BLOCK"]


class ChangeRequest(BaseModel):
    asset_urn: str = Field(min_length=3, max_length=1_000)
    column: str = Field(min_length=1, max_length=255)
    change_type: ChangeType
    new_value: str | None = Field(default=None, max_length=255)
    reason: str = Field(default="", max_length=500)

    @field_validator("asset_urn", "column", "reason", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("asset_urn")
    @classmethod
    def validate_datahub_urn(cls, value: str) -> str:
        if not value.startswith("urn:li:"):
            raise ValueError("asset_urn must be a valid DataHub URN")
        return value

    @field_validator("new_value", mode="before")
    @classmethod
    def normalize_new_value(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def validate_new_value(self) -> "ChangeRequest":
        if self.change_type in {"rename", "type_change", "add"} and not self.new_value:
            raise ValueError(
                "new_value is required for rename, type_change, and add"
            )
        if self.change_type == "rename" and self.new_value == self.column:
            raise ValueError("new_value must differ from column for rename")
        if self.change_type == "drop":
            self.new_value = None
        return self


class Asset(BaseModel):
    urn: str
    name: str
    asset_type: str
    platform: str
    owners: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    criticality: Literal["low", "medium", "high", "critical"] = "medium"
    usage_score: int = Field(default=0, ge=0, le=100)
    fields: list[str] = Field(default_factory=list)
    quality_status: Literal["passing", "warning", "failing", "unknown"] = "unknown"
    dependency_type: str = "downstream"
    hops: int = Field(default=1, ge=0, le=10)


class LineageEdge(BaseModel):
    source: str
    target: str
    via_column: str | None = None
    dependency_type: str = "column"


class ContextGraph(BaseModel):
    root_asset: Asset
    assets: list[Asset]
    edges: list[LineageEdge]
    glossary_terms: list[str] = Field(default_factory=list)
    context_notes: list[str] = Field(default_factory=list)


class RiskFactor(BaseModel):
    label: str
    points: int
    evidence: str


class GeneratedArtifacts(BaseModel):
    migration_sql: str
    compatibility_sql: str
    data_tests_yaml: str
    rollback_plan: list[str]
    pull_request_summary: str


class AnalysisResult(BaseModel):
    analysis_id: str
    provider: str
    decision: Decision
    risk_score: int
    raw_risk_score: int
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    factors: list[RiskFactor]
    affected_assets: list[Asset]
    required_approvals: list[str]
    explanation: str
    artifacts: GeneratedArtifacts
    root_asset: Asset
    lineage_edges: list[LineageEdge]
    context_notes: list[str] = Field(default_factory=list)
