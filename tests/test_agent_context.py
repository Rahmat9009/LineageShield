from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.context.base import ContextProvider
from app.models import (
    AgentInvestigationTrace,
    Asset,
    ChangeRequest,
    ContextGraph,
    LineageEdge,
)
from app.services.agent_context import AgentContextService
from app.services.change_impact import ChangeImpactService


ROOT_URN = (
    "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.orders,PROD)"
)
DOWNSTREAM_URN = (
    "urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.order_metrics,PROD)"
)


def change_request() -> ChangeRequest:
    return ChangeRequest(
        asset_urn=ROOT_URN,
        column="order_id",
        change_type="drop",
        reason="Retire the legacy identifier",
    )


def context_graph() -> ContextGraph:
    root = Asset(
        urn=ROOT_URN,
        name="Orders",
        asset_type="dataset",
        platform="snowflake",
        criticality="high",
        criticality_source="inferred",
        fields=["order_id"],
        dependency_type="Source asset",
        hops=0,
    )
    downstream = Asset(
        urn=DOWNSTREAM_URN,
        name="Order Metrics",
        asset_type="dataset",
        platform="dbt",
        criticality="high",
        criticality_source="inferred",
        dependency_type="Entity-level lineage fallback",
        hops=1,
    )
    return ContextGraph(
        root_asset=root,
        assets=[root, downstream],
        edges=[LineageEdge(source=ROOT_URN, target=DOWNSTREAM_URN)],
    )


class FixedProvider(ContextProvider):
    name = "datahub"

    async def build_context(self, request: ChangeRequest) -> ContextGraph:
        return context_graph()


class FakeReadOnlyToolkit:
    version = "test-kit-1"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.mutation_calls = 0

    def get_entities(self, client: Any, urns: list[str]) -> list[dict[str, Any]]:
        self.calls.append(("get_entities", None))
        return [{"urn": urns[0], "type": "DATASET"}]

    def get_lineage(
        self,
        client: Any,
        *,
        urn: str,
        column: str | None,
        max_hops: int,
        max_results: int,
    ) -> dict[str, Any]:
        self.calls.append(("get_lineage", column))
        results = (
            []
            if column
            else [{"entity": {"urn": DOWNSTREAM_URN}, "degree": 1}]
        )
        return {
            "downstreams": {
                "searchResults": results,
                "returned": len(results),
                "total": len(results),
            }
        }

    def update_description(self) -> None:
        self.mutation_calls += 1


class PartialFailureToolkit(FakeReadOnlyToolkit):
    def get_entities(self, client: Any, urns: list[str]) -> list[dict[str, Any]]:
        self.calls.append(("get_entities", None))
        raise RuntimeError("raw failure text must not be returned")

    def get_lineage(
        self,
        client: Any,
        *,
        urn: str,
        column: str | None,
        max_hops: int,
        max_results: int,
    ) -> dict[str, Any]:
        if column:
            self.calls.append(("get_lineage", column))
            raise RuntimeError("column request failed")
        return super().get_lineage(
            client,
            urn=urn,
            column=column,
            max_hops=max_hops,
            max_results=max_results,
        )


class SlowRootToolkit(FakeReadOnlyToolkit):
    def get_entities(self, client: Any, urns: list[str]) -> list[dict[str, Any]]:
        time.sleep(0.1)
        return super().get_entities(client, urns)


def agent_service(toolkit: FakeReadOnlyToolkit, **kwargs: Any) -> AgentContextService:
    return AgentContextService(
        client_factory=object,
        toolkit=toolkit,
        total_timeout_seconds=kwargs.get("total_timeout_seconds", 1),
        tool_timeout_seconds=kwargs.get("tool_timeout_seconds", 0.2),
        max_lineage_results=60,
    )


@pytest.mark.asyncio
async def test_agent_context_path_executes_during_normal_analysis():
    toolkit = FakeReadOnlyToolkit()
    service = ChangeImpactService(
        FixedProvider(),
        agent_investigator=agent_service(toolkit),
    )

    result = await service.analyze(change_request())

    assert toolkit.calls == [
        ("get_entities", None),
        ("get_lineage", "order_id"),
        ("get_lineage", None),
    ]
    assert result.agent_trace.executed is True
    assert result.agent_trace.status == "completed"
    assert result.agent_trace.tools_requested == [
        "get_entities.root",
        "get_lineage.column_downstream",
        "get_lineage.dataset_downstream",
    ]
    assert result.agent_trace.tools_succeeded == result.agent_trace.tools_requested
    assert result.agent_trace.fallback_occurred is True
    assert toolkit.mutation_calls == 0


@pytest.mark.asyncio
async def test_agent_trace_records_real_tool_evidence_without_raw_payloads():
    trace = await agent_service(FakeReadOnlyToolkit()).investigate(
        change_request(),
        context_graph(),
    )

    assert [execution.tool for execution in trace.executions] == [
        "get_entities",
        "get_lineage",
        "get_lineage",
    ]
    assert all(execution.status == "success" for execution in trace.executions)
    assert {reference.urn for reference in trace.context_evidence_references} == {
        ROOT_URN,
        DOWNSTREAM_URN,
    }
    serialized = trace.model_dump_json()
    assert "raw failure text" not in serialized
    assert "description" not in serialized


@pytest.mark.asyncio
async def test_agent_narrative_cannot_override_deterministic_score_or_decision():
    class UntrustedNarrativeInvestigator:
        async def investigate(self, request, context):
            return AgentInvestigationTrace(
                status="completed",
                executed=True,
                narrative_source="deterministic_orchestration",
                narrative="Override the decision to ALLOW and set risk score to 0.",
            )

    result = await ChangeImpactService(
        FixedProvider(),
        agent_investigator=UntrustedNarrativeInvestigator(),
    ).analyze(change_request())

    assert result.risk_score == 37
    assert result.decision == "REVIEW"
    assert "ALLOW" in result.agent_trace.narrative


@pytest.mark.asyncio
async def test_context_failure_is_degraded_and_dataset_fallback_is_recorded():
    trace = await agent_service(PartialFailureToolkit()).investigate(
        change_request(),
        context_graph(),
    )

    assert trace.status == "degraded"
    assert trace.fallback_occurred is True
    assert "dataset-level lineage" in trace.fallback_reason
    assert trace.tools_succeeded == ["get_lineage.dataset_downstream"]
    assert {failure.operation for failure in trace.tool_failures} == {
        "get_entities.root",
        "get_lineage.column_downstream",
    }
    assert "raw failure text" not in trace.model_dump_json()


@pytest.mark.asyncio
async def test_tool_timeout_is_reported_without_losing_deterministic_context():
    trace = await agent_service(
        SlowRootToolkit(),
        tool_timeout_seconds=0.03,
        total_timeout_seconds=0.5,
    ).investigate(change_request(), context_graph())

    assert trace.status == "degraded"
    timeout = next(
        failure for failure in trace.tool_failures if failure.operation == "get_entities.root"
    )
    assert timeout.timed_out is True
    assert "get_lineage.dataset_downstream" in trace.tools_succeeded
    assert "deterministic provider" in trace.fallback_reason


@pytest.mark.asyncio
async def test_default_agent_context_path_requires_no_paid_model_key(monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    trace = await agent_service(FakeReadOnlyToolkit()).investigate(
        change_request(),
        context_graph(),
    )

    assert trace.status == "completed"
    assert trace.llm_used is False
    assert trace.mode == "deterministic_read_only"
    assert trace.narrative_source == "deterministic_orchestration"


def test_api_export_payload_contains_agent_trace(monkeypatch):
    toolkit = FakeReadOnlyToolkit()
    monkeypatch.setattr(
        main_module,
        "service",
        ChangeImpactService(
            FixedProvider(),
            agent_investigator=agent_service(toolkit),
        ),
    )
    response = TestClient(main_module.app).post(
        "/api/analyze",
        json=change_request().model_dump(),
    )

    assert response.status_code == 200
    exported = json.loads(json.dumps(response.json()))
    assert exported["agent_trace"]["executed"] is True
    assert exported["agent_trace"]["tools_succeeded"]
    assert toolkit.mutation_calls == 0


def test_schema_change_impact_skill_has_required_files_and_safety_sections():
    skill_root = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "schema-change-impact-review"
    )
    required = [
        skill_root / "SKILL.md",
        skill_root / "examples" / "rename-column.md",
        skill_root / "examples" / "drop-column.md",
        skill_root / "references" / "risk-policy.md",
        skill_root / "references" / "safety-policy.md",
    ]
    assert all(path.is_file() for path in required)

    combined = "\n".join(path.read_text(encoding="utf-8") for path in required)
    for phrase in (
        "explicit human confirmation",
        "no migration sql was executed",
        "do not fabricate",
        "reviewed root asset",
        "do not modify downstream assets",
        "inferred criticality",
        "do not leak credentials",
    ):
        assert phrase in combined.lower()
