from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


ChangeType = Literal["rename", "drop", "type_change", "add"]
Decision = Literal["ALLOW", "REVIEW", "BLOCK"]
MetadataSource = Literal[
    "datahub",
    "lineage",
    "inferred",
    "fallback",
    "unavailable",
    "demo",
]
MetadataValue = str | int | float | bool


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


class AssetOwner(BaseModel):
    urn: str
    label: str
    ownership_type: str | None = None
    ownership_type_urn: str | None = None


class Asset(BaseModel):
    urn: str
    name: str
    asset_type: str
    platform: str
    description: str | None = None
    owners: list[str] = Field(default_factory=list)
    owner_urns: list[str] = Field(default_factory=list)
    owner_details: list[AssetOwner] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    tag_urns: list[str] = Field(default_factory=list)
    glossary_terms: list[str] = Field(default_factory=list)
    glossary_term_urns: list[str] = Field(default_factory=list)
    structured_properties: dict[str, list[MetadataValue]] = Field(
        default_factory=dict
    )
    criticality: Literal["low", "medium", "high", "critical"] = "medium"
    criticality_source: MetadataSource = "unavailable"
    criticality_evidence: str = "No criticality evidence was available."
    usage_score: int = Field(default=0, ge=0, le=100)
    usage_evidence: str = "No trustworthy normalized usage score was available."
    fields: list[str] = Field(default_factory=list)
    quality_status: Literal["passing", "warning", "failing", "unknown"] = "unknown"
    quality_evidence: str = "No reliable DataHub quality signal was available."
    metadata_sources: dict[str, MetadataSource] = Field(default_factory=dict)
    dependency_type: str = "downstream"
    hops: int = Field(default=1, ge=0, le=10)


class LineageEdge(BaseModel):
    source: str
    target: str
    via_column: str | None = None
    dependency_type: str = "column"


class MetadataSummary(BaseModel):
    """Coverage counts for the root plus every unique downstream asset."""

    total_assets: int = Field(default=0, ge=0)
    datahub_entities_enriched: int = Field(default=0, ge=0)
    assets_with_owners: int = Field(default=0, ge=0)
    assets_with_tags: int = Field(default=0, ge=0)
    assets_with_schema_fields: int = Field(default=0, ge=0)
    assets_with_glossary_terms: int = Field(default=0, ge=0)
    assets_with_quality_signals: int = Field(default=0, ge=0)
    assets_with_usage_information: int = Field(default=0, ge=0)
    assets_with_explicit_criticality: int = Field(default=0, ge=0)
    enrichment_failures: int = Field(default=0, ge=0)


class ContextGraph(BaseModel):
    root_asset: Asset
    assets: list[Asset]
    edges: list[LineageEdge]
    glossary_terms: list[str] = Field(default_factory=list)
    metadata_summary: MetadataSummary = Field(default_factory=MetadataSummary)
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
    glossary_terms: list[str] = Field(default_factory=list)
    metadata_summary: MetadataSummary = Field(default_factory=MetadataSummary)
    context_notes: list[str] = Field(default_factory=list)
