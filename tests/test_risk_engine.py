import pytest

from app.context.demo_provider import DemoContextProvider
from app.models import ChangeRequest
from app.services.change_impact import ChangeImpactService


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
