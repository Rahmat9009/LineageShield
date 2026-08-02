from types import SimpleNamespace
import time

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


class FakeGraph:
    def __init__(self, entities=None, delays=None):
        self.entities = entities or {}
        self.delays = delays or {}
        self.calls: list[tuple[str, list[str]]] = []

    def get_entities(self, entity_type, urns):
        self.calls.append((entity_type, list(urns)))
        if delay := self.delays.get(entity_type):
            time.sleep(delay)
        return {
            urn: self.entities[urn]
            for urn in urns
            if urn in self.entities
        }


class EnrichingFakeClient(FakeClient):
    def __init__(self, column_results, entities, entity_results=(), delays=None):
        super().__init__(column_results, entity_results)
        self._graph = FakeGraph(entities, delays)


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


@pytest.mark.asyncio
async def test_root_entity_is_enriched_from_real_aspect_shapes():
    owner_urn = "urn:li:corpGroup:data-platform"
    tag_urn = "urn:li:tag:governance.pii"
    term_urn = "urn:li:glossaryTerm:customer-data"
    entities = {
        SOURCE_URN: {
            "datasetProperties": SimpleNamespace(
                name="Production Orders",
                description="Canonical order records.",
                customProperties={},
            ),
            "dataPlatformInstance": SimpleNamespace(
                platform="urn:li:dataPlatform:snowflake"
            ),
            "ownership": SimpleNamespace(
                owners=[
                    SimpleNamespace(owner=owner_urn),
                    SimpleNamespace(owner=owner_urn),
                ]
            ),
            "globalTags": SimpleNamespace(tags=[SimpleNamespace(tag=tag_urn)]),
            "glossaryTerms": SimpleNamespace(
                terms=[SimpleNamespace(urn=term_urn)]
            ),
            "schemaMetadata": SimpleNamespace(
                fields=[
                    SimpleNamespace(fieldPath="order_id"),
                    SimpleNamespace(fieldPath="order_total"),
                ]
            ),
            "structuredProperties": SimpleNamespace(
                properties=[
                    SimpleNamespace(
                        propertyUrn="urn:li:structuredProperty:criticality",
                        values=["critical"],
                    )
                ]
            ),
            "testResults": SimpleNamespace(
                passing=[SimpleNamespace(test="urn:li:test:quality-assertions")],
                failing=[],
            ),
        },
        owner_urn: {"corpGroupInfo": SimpleNamespace(displayName="Data Platform")},
        tag_urn: {"tagProperties": SimpleNamespace(name="PII")},
        term_urn: {
            "glossaryTermInfo": SimpleNamespace(name="Customer Data")
        },
    }
    client = EnrichingFakeClient(column_results=(), entities=entities)
    provider = DataHubContextProvider(client=client)
    request = ChangeRequest(
        asset_urn=SOURCE_URN,
        column="order_id",
        change_type="rename",
        new_value="purchase_id",
    )

    context = await provider.build_context(request)

    root = context.root_asset
    assert root.name == "Production Orders"
    assert root.description == "Canonical order records."
    assert root.platform == "snowflake"
    assert root.fields == ["order_id", "order_total"]
    assert root.owners == ["Data Platform"]
    assert root.owner_urns == [owner_urn]
    assert root.tags == ["PII"]
    assert root.glossary_terms == ["Customer Data"]
    assert root.quality_status == "passing"
    assert root.criticality == "critical"
    assert root.criticality_source == "datahub"
    assert root.metadata_sources["entity"] == "datahub"
    assert context.glossary_terms == ["Customer Data"]
    assert context.metadata_summary.datahub_entities_enriched == 1
    assert context.metadata_summary.assets_with_schema_fields == 1


@pytest.mark.asyncio
async def test_downstream_enrichment_failure_is_isolated():
    good_urn = DOWNSTREAM_URN
    missing_urn = (
        "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.missing,PROD)"
    )
    results = (
        lineage_result(good_urn, "lineage_good"),
        lineage_result(missing_urn, "lineage_missing"),
    )
    entities = {
        SOURCE_URN: {"datasetProperties": SimpleNamespace(name="Orders")},
        good_urn: {"datasetProperties": SimpleNamespace(name="Enriched Consumer")},
    }
    client = EnrichingFakeClient(column_results=results, entities=entities)
    provider = DataHubContextProvider(client=client)
    request = ChangeRequest(
        asset_urn=SOURCE_URN,
        column="order_id",
        change_type="rename",
        new_value="purchase_id",
    )

    context = await provider.build_context(request)
    by_urn = {asset.urn: asset for asset in context.assets}

    assert by_urn[good_urn].name == "Enriched Consumer"
    assert by_urn[good_urn].metadata_sources["entity"] == "datahub"
    assert by_urn[missing_urn].name == "Lineage Missing"
    assert "entity" not in by_urn[missing_urn].metadata_sources
    assert context.metadata_summary.enrichment_failures == 1


@pytest.mark.asyncio
async def test_timeout_preserves_metadata_from_other_entity_types():
    dashboard_urn = "urn:li:dashboard:(looker,orders_overview)"
    dashboard_result = SimpleNamespace(
        urn=dashboard_urn,
        name="orders_overview",
        type="DASHBOARD",
        platform="looker",
        hops=1,
    )
    entities = {
        SOURCE_URN: {"datasetProperties": SimpleNamespace(name="Orders Live")},
        dashboard_urn: {"dashboardInfo": SimpleNamespace(title="Orders Overview")},
    }
    client = EnrichingFakeClient(
        column_results=(dashboard_result,),
        entities=entities,
        delays={"dashboard": 0.1},
    )
    provider = DataHubContextProvider(
        client=client,
        enrichment_timeout_seconds=0.2,
        enrichment_request_timeout_seconds=0.04,
    )
    request = ChangeRequest(
        asset_urn=SOURCE_URN,
        column="order_id",
        change_type="rename",
        new_value="purchase_id",
    )

    context = await provider.build_context(request)

    assert context.root_asset.name == "Orders Live"
    assert context.assets[1].name == "Orders Overview"
    assert "entity" not in context.assets[1].metadata_sources
    assert context.metadata_summary.enrichment_failures == 1
