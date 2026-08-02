import pytest

from app.context.base import ContextProvider
from app.models import Asset, ChangeRequest, ContextGraph
from app.services.change_impact import ChangeImpactService


class OwnedContextProvider(ContextProvider):
    name = "mock-datahub"

    async def healthcheck(self) -> tuple[bool, str]:
        return True, "Ready"

    async def build_context(self, request: ChangeRequest) -> ContextGraph:
        root = Asset(
            urn=request.asset_urn,
            name="Orders",
            asset_type="dataset",
            platform="snowflake",
            criticality="high",
            criticality_source="inferred",
            dependency_type="Source asset",
            hops=0,
        )
        affected = Asset(
            urn="urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.orders,PROD)",
            name="Orders Model",
            asset_type="dataset",
            platform="dbt",
            owners=["Data Platform", "Data Platform"],
            owner_urns=["urn:li:corpGroup:data-platform"],
            criticality="high",
            criticality_source="inferred",
            metadata_sources={"owners": "datahub", "owner_labels": "datahub"},
        )
        return ContextGraph(root_asset=root, assets=[root, affected], edges=[])


@pytest.mark.asyncio
async def test_required_approvals_use_normalized_real_owner_values():
    service = ChangeImpactService(OwnedContextProvider())
    request = ChangeRequest(
        asset_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,raw.orders,PROD)",
        column="order_id",
        change_type="rename",
        new_value="purchase_id",
    )

    result = await service.analyze(request)

    assert result.required_approvals == ["Data Platform"]
    owner_factor = next(
        factor for factor in result.factors if factor.label == "Cross-team coordination"
    )
    assert owner_factor.evidence == "1 owner(s): Data Platform"
