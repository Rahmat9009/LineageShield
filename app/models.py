from typing import Literal
from pydantic import BaseModel, Field, model_validator


ChangeType = Literal["rename", "drop", "type_change", "add"]
Decision = Literal["ALLOW", "REVIEW", "BLOCK"]


class ChangeRequest(BaseModel):
    asset_urn: str = Field(min_length=3)
    column: str = Field(min_length=1)
    change_type: ChangeType
    new_value: str | None = None
    reason: str = ""

    @model_validator(mode="after")
    def validate_new_value(self):
        if self.change_type in {"rename", "type_change"} and not self.new_value:
            raise ValueError("new_value is required for rename and type_change")
        return self


class Asset(BaseModel):
    urn: str
    name: str
    asset_type: str
    platform: str
    owners: list[str] = []
    tags: list[str] = []
    criticality: Literal["low", "medium", "high", "critical"] = "medium"
    usage_score: int = Field(default=0, ge=0, le=100)
    fields: list[str] = []
    quality_status: Literal["passing", "warning", "failing", "unknown"] = "unknown"


class LineageEdge(BaseModel):
    source: str
    target: str
    via_column: str | None = None


class ContextGraph(BaseModel):
    root_asset: Asset
    assets: list[Asset]
    edges: list[LineageEdge]
    glossary_terms: list[str] = []
    context_notes: list[str] = []


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
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    factors: list[RiskFactor]
    affected_assets: list[Asset]
    required_approvals: list[str]
    explanation: str
    artifacts: GeneratedArtifacts
