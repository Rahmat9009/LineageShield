from fastapi.testclient import TestClient

import app.main as main_module
from app.context.base import ContextProvider
from app.models import Asset, ChangeRequest, ContextGraph, LineageEdge
from app.services.change_impact import ChangeImpactService


class MockContextProvider(ContextProvider):
    name = "mock-datahub"

    async def healthcheck(self) -> tuple[bool, str]:
        return True, "Mock live context is ready."

    async def build_context(self, request: ChangeRequest) -> ContextGraph:
        root = Asset(
            urn=request.asset_urn,
            name="Orders",
            asset_type="dataset",
            platform="snowflake",
            criticality="high",
            fields=[request.column],
            dependency_type="Source asset",
            hops=0,
        )
        downstream = Asset(
            urn="urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.order_metrics,PROD)",
            name="Order Metrics",
            asset_type="pipeline",
            platform="dbt",
            criticality="medium",
            dependency_type="Column-level lineage",
            hops=1,
        )
        edge = LineageEdge(
            source=root.urn,
            target=downstream.urn,
            via_column=request.column,
        )
        return ContextGraph(
            root_asset=root,
            assets=[root, downstream],
            edges=[edge],
            context_notes=["Mocked provider evidence."],
        )


def test_health_endpoint_uses_provider_healthcheck(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "service",
        ChangeImpactService(MockContextProvider()),
    )
    client = TestClient(main_module.app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app": main_module.settings.app_name,
        "context_provider": "mock-datahub",
        "provider": "mock-datahub",
        "connected": True,
        "detail": "Mock live context is ready.",
    }


def test_analyze_endpoint_with_mocked_provider(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "service",
        ChangeImpactService(MockContextProvider()),
    )
    client = TestClient(main_module.app)
    payload = {
        "asset_urn": (
            "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.orders,PROD)"
        ),
        "column": "order_id",
        "change_type": "rename",
        "new_value": "purchase_id",
        "reason": "Standardize identifiers",
    }

    response = client.post("/api/analyze", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock-datahub"
    assert body["decision"] == "ALLOW"
    assert body["root_asset"]["name"] == "Orders"
    assert body["affected_assets"][0]["name"] == "Order Metrics"
    assert body["lineage_edges"][0]["via_column"] == "order_id"
    assert body["raw_risk_score"] == body["risk_score"]
