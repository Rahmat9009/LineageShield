from types import SimpleNamespace

import pytest

from app.context.datahub_provider import DataHubContextProvider
from app.models import ChangeRequest


SOURCE_URN = (
    "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.orders,PROD)"
)
DOWNSTREAM_URN = (
    "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.order_metrics,PROD)"
)


class FakeLineage:
    def __init__(self, column_results, entity_results):
        self.column_results = column_results
        self.entity_results = entity_results
        self.calls: list[dict] = []

    def get_lineage(self, **kwargs):
        self.calls.append(kwargs)
        if "source_column" in kwargs:
            return iter(self.column_results)
        return iter(self.entity_results)


class FakeClient:
    def __init__(self, column_results, entity_results=()):
        self.lineage = FakeLineage(column_results, entity_results)
        self.connection_checks = 0

    def test_connection(self):
        self.connection_checks += 1


def lineage_result(urn: str = DOWNSTREAM_URN, name=None):
    return SimpleNamespace(
        urn=urn,
        name=name,
        type="DATASET",
        platform="urn:li:dataPlatform:snowflake",
        hops=1,
    )


def test_column_lineage_falls_back_to_entity_lineage():
    entity_result = lineage_result()
    client = FakeClient(column_results=(), entity_results=(entity_result,))
    provider = DataHubContextProvider(client=client)

    results, source = provider._fetch_downstream_lineage(SOURCE_URN, "order_id")

    assert source == "entity"
    assert results == [entity_result]
    assert len(client.lineage.calls) == 2
    assert client.lineage.calls[0]["source_column"] == "order_id"
    assert "source_column" not in client.lineage.calls[1]


@pytest.mark.asyncio
async def test_duplicate_lineage_results_are_removed():
    duplicate = lineage_result()
    client = FakeClient(column_results=(duplicate, duplicate))
    provider = DataHubContextProvider(client=client)
    request = ChangeRequest(
        asset_urn=SOURCE_URN,
        column="order_id",
        change_type="rename",
        new_value="purchase_id",
    )

    context = await provider.build_context(request)

    assert client.connection_checks == 1
    assert len(context.assets) == 2
    assert context.assets[1].urn == DOWNSTREAM_URN
    assert context.assets[1].name == "Order Metrics"
    assert context.edges[0].dependency_type == "column"


@pytest.mark.parametrize(
    ("urn", "expected"),
    [
        (
            "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)",
            "Order Details",
        ),
        ("urn:li:dashboard:(looker,regional_sales)", "Regional Sales"),
        ("urn:li:chart:(looker,inventory_health)", "Inventory Health"),
        (
            "urn:li:dataJob:(urn:li:dataFlow:(airflow,orders,PROD),refresh_orders)",
            "Refresh Orders",
        ),
        ("urn:li:dataFlow:(airflow,orders_daily,PROD)", "Orders Daily"),
    ],
)
def test_urn_fallback_names_are_human_readable(urn: str, expected: str):
    assert DataHubContextProvider._name_from_urn(urn) == expected
