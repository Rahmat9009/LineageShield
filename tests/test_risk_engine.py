import pytest

from app.context.demo_provider import DemoContextProvider
from app.context.base import ContextProvider
from app.models import Asset, ChangeRequest, ContextGraph, LineageEdge
from app.services.change_impact import ChangeImpactService
from app.services.risk_engine import RiskEngine


@pytest.mark.asyncio
async def test_demo_change_is_blocked():
    service = ChangeImpactService(DemoContextProvider())
    request = ChangeRequest(
        asset_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,prod.customers,PROD)",
        column="customer_region",
        change_type="rename",
        new_value="sales_region",
    )

    result = await service.analyze(request)

    assert result.decision == "BLOCK"
    assert result.risk_score >= 75
    assert any(a.asset_type == "dashboard" for a in result.affected_assets)
    assert any(a.asset_type == "ml_model" for a in result.affected_assets)
    assert "ALTER TABLE" in result.artifacts.migration_sql
    assert result.raw_risk_score >= result.risk_score
    assert result.root_asset.urn == request.asset_urn
    assert result.lineage_edges


def make_context(affected_assets: list[Asset]) -> ContextGraph:
    root = Asset(
        urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.orders,PROD)",
        name="Orders",
        asset_type="dataset",
        platform="snowflake",
        criticality="high",
        dependency_type="Source asset",
        hops=0,
    )
    edges = [
        LineageEdge(source=root.urn, target=asset.urn)
        for asset in affected_assets
    ]
    return ContextGraph(
        root_asset=root,
        assets=[root, *affected_assets],
        edges=edges,
    )


def test_large_blast_radius_has_explainable_factor():
    affected = [
        Asset(
            urn=f"urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.consumer_{index},PROD)",
            name=f"Consumer {index}",
            asset_type="dataset",
            platform="snowflake",
            criticality="medium",
        )
        for index in range(12)
    ]
    request = ChangeRequest(
        asset_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.orders,PROD)",
        column="order_id",
        change_type="drop",
    )

    score, factors, returned_assets = RiskEngine().evaluate(
        request,
        make_context(affected),
    )

    blast_radius = next(
        factor for factor in factors if factor.label == "Large downstream blast radius"
    )
    assert len(returned_assets) == 12
    assert blast_radius.points == 20
    assert "12 downstream assets" in blast_radius.evidence
    assert score == 45


@pytest.mark.parametrize(
    ("score", "decision", "risk_level"),
    [
        (0, "ALLOW", "LOW"),
        (24, "ALLOW", "LOW"),
        (25, "REVIEW", "MEDIUM"),
        (49, "REVIEW", "MEDIUM"),
        (50, "BLOCK", "HIGH"),
        (74, "BLOCK", "HIGH"),
        (75, "BLOCK", "CRITICAL"),
        (100, "BLOCK", "CRITICAL"),
    ],
)
def test_decision_thresholds(score: int, decision: str, risk_level: str):
    assert ChangeImpactService.classify_score(score) == (decision, risk_level)
