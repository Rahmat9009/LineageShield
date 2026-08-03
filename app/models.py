from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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

AgentTraceStatus = Literal["completed", "degraded", "unavailable"]
AgentToolStatus = Literal["success", "failure", "timeout"]
AgentNarrativeSource = Literal[
    "deterministic_orchestration",
    "optional_model",
    "unavailable",
]


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


class AgentToolFailure(BaseModel):
    tool: str
    operation: str
    error_type: str
    message: str
    timed_out: bool = False


class AgentToolExecution(BaseModel):
    tool: str
    operation: str
    status: AgentToolStatus
    duration_ms: int = Field(default=0, ge=0)
    result_summary: str
    evidence_references: list[str] = Field(default_factory=list)


class AgentEvidenceReference(BaseModel):
    urn: str
    label: str
    evidence_type: Literal[
        "root_entity",
        "column_lineage",
        "dataset_lineage",
    ]
    source: Literal["datahub_agent_context"] = "datahub_agent_context"


class AgentInvestigationTrace(BaseModel):
    """Sanitized audit trace for the read-only Agent Context Kit workflow."""

    status: AgentTraceStatus = "unavailable"
    executed: bool = False
    toolkit: Literal["datahub-agent-context"] = "datahub-agent-context"
    toolkit_version: str | None = None
    mode: Literal["deterministic_read_only"] = "deterministic_read_only"
    llm_used: Literal[False] = False
    narrative_source: AgentNarrativeSource = "unavailable"
    tools_requested: list[str] = Field(default_factory=list)
    tools_succeeded: list[str] = Field(default_factory=list)
    tool_failures: list[AgentToolFailure] = Field(default_factory=list)
    executions: list[AgentToolExecution] = Field(default_factory=list)
    fallback_occurred: bool = False
    fallback_reason: str | None = None
    duration_ms: int = Field(default=0, ge=0)
    context_evidence_references: list[AgentEvidenceReference] = Field(
        default_factory=list
    )
    narrative: str = (
        "Agent Context Kit did not execute; deterministic LineageShield analysis "
        "remained available."
    )
    limitations: list[str] = Field(default_factory=list)


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
    agent_trace: AgentInvestigationTrace = Field(
        default_factory=AgentInvestigationTrace
    )


class WritebackTarget(BaseModel):
    urn: str
    name: str
    platform: str


class ProposedChangeRecord(BaseModel):
    change_type: ChangeType
    column: str
    new_value: str | None = None
    reason: str = ""


class WritebackRecord(BaseModel):
    analysis_id: str
    analysis_timestamp: datetime
    root_asset: WritebackTarget
    proposed_change: ProposedChangeRecord
    decision: Decision
    risk_score: int = Field(ge=0, le=100)
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    affected_asset_count: int = Field(ge=0)
    required_approvals: list[str] = Field(default_factory=list)
    rationale: str
    evidence_summary: list[str] = Field(default_factory=list)
    migration_summary: str
    rollback_summary: str
    no_migration_executed: Literal[True] = True


class WritebackPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str = Field(min_length=1, max_length=100)


class WritebackApplyRequest(WritebackPreviewRequest):
    confirmation: Literal["RECORD_IN_DATAHUB"]


class DataHubMutationPreview(BaseModel):
    operation: Literal["patch_editable_description"] = "patch_editable_description"
    aspect: Literal["editableDatasetProperties"] = "editableDatasetProperties"
    field: Literal["description"] = "description"
    managed_section: str
    resulting_description: str
    already_applied: bool = False
    preserves_existing_description: Literal[True] = True


class WritebackPreview(BaseModel):
    mutations_enabled: bool
    expires_at: datetime
    record: WritebackRecord
    mutation: DataHubMutationPreview
    warnings: list[str] = Field(default_factory=list)


class WritebackReceipt(BaseModel):
    analysis_id: str
    asset: WritebackTarget
    operation: Literal["patch_editable_description"] = "patch_editable_description"
    aspect: Literal["editableDatasetProperties"] = "editableDatasetProperties"
    applied_at: datetime
    status: Literal["applied", "already_applied"]
    idempotent: bool
    mutation_state: Literal["confirmed"] = "confirmed"
    message: str
