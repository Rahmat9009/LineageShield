from types import SimpleNamespace

from app.context.datahub_metadata import (
    apply_reference_labels,
    enrich_asset_from_aspects,
)
from app.models import Asset


ASSET_URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.orders,PROD)"
OWNER_USER_URN = "urn:li:corpuser:alice.smith@example.com"
OWNER_GROUP_URN = "urn:li:corpGroup:data-platform"
OWNERSHIP_TYPE_URN = "urn:li:ownershipType:technical-owner"
TAG_URN = "urn:li:tag:governance.pii"
TERM_URN = "urn:li:glossaryTerm:customer-data"


def baseline_asset() -> Asset:
    return Asset(
        urn=ASSET_URN,
        name="Orders",
        asset_type="dataset",
        platform="snowflake",
        criticality="high",
        criticality_source="inferred",
        criticality_evidence="Deterministic fallback.",
        metadata_sources={
            "criticality": "inferred",
            "quality": "unavailable",
            "usage": "unavailable",
        },
    )


def test_owner_normalization_and_deduplication():
    asset = enrich_asset_from_aspects(
        baseline_asset(),
        {
            "ownership": SimpleNamespace(
                owners=[
                    SimpleNamespace(
                        owner=OWNER_USER_URN,
                        typeUrn=OWNERSHIP_TYPE_URN,
                    ),
                    SimpleNamespace(
                        owner=OWNER_USER_URN,
                        typeUrn=OWNERSHIP_TYPE_URN,
                    ),
                    SimpleNamespace(owner=OWNER_GROUP_URN),
                ]
            )
        },
    )

    resolved = apply_reference_labels(
        asset,
        owner_labels={
            OWNER_USER_URN: "Alice Smith",
            OWNER_GROUP_URN: "Data Platform",
        },
        ownership_type_labels={OWNERSHIP_TYPE_URN: "Technical Owner"},
        tag_labels={},
        term_labels={},
    )

    assert resolved.owner_urns == [OWNER_USER_URN, OWNER_GROUP_URN]
    assert resolved.owners == ["Alice Smith", "Data Platform"]
    assert resolved.owner_details[0].ownership_type == "Technical Owner"
    assert resolved.owner_details[0].ownership_type_urn == OWNERSHIP_TYPE_URN
    assert resolved.metadata_sources["owners"] == "datahub"
    assert resolved.metadata_sources["owner_labels"] == "datahub"


def test_tag_and_glossary_normalization_and_deduplication():
    asset = enrich_asset_from_aspects(
        baseline_asset(),
        {
            "globalTags": SimpleNamespace(
                tags=[SimpleNamespace(tag=TAG_URN), SimpleNamespace(tag=TAG_URN)]
            ),
            "glossaryTerms": SimpleNamespace(
                terms=[
                    SimpleNamespace(urn=TERM_URN),
                    SimpleNamespace(urn=TERM_URN),
                ]
            ),
        },
    )

    resolved = apply_reference_labels(
        asset,
        owner_labels={},
        ownership_type_labels={},
        tag_labels={TAG_URN: "PII"},
        term_labels={TERM_URN: "Customer Data"},
    )

    assert resolved.tag_urns == [TAG_URN]
    assert resolved.tags == ["PII"]
    assert resolved.glossary_term_urns == [TERM_URN]
    assert resolved.glossary_terms == ["Customer Data"]
    assert resolved.metadata_sources["tag_labels"] == "datahub"
    assert resolved.metadata_sources["glossary_term_labels"] == "datahub"


def test_explicit_criticality_overrides_inferred_criticality():
    explicit = enrich_asset_from_aspects(
        baseline_asset(),
        {
            "structuredProperties": SimpleNamespace(
                properties=[
                    SimpleNamespace(
                        propertyUrn="urn:li:structuredProperty:governance.criticality",
                        values=["critical"],
                    )
                ]
            )
        },
    )
    inferred = enrich_asset_from_aspects(
        baseline_asset(),
        {"datasetProperties": SimpleNamespace(name="Orders")},
    )

    assert explicit.criticality == "critical"
    assert explicit.criticality_source == "datahub"
    assert "structured property" in explicit.criticality_evidence
    assert inferred.criticality == "high"
    assert inferred.criticality_source == "inferred"


def test_missing_quality_and_usage_remain_truthfully_unavailable():
    asset = enrich_asset_from_aspects(
        baseline_asset(),
        {
            "datasetProperties": SimpleNamespace(name="Orders"),
            "testResults": SimpleNamespace(
                passing=[SimpleNamespace(test="urn:li:test:cost-policy")],
                failing=[],
            ),
        },
    )

    assert asset.quality_status == "unknown"
    assert asset.metadata_sources["quality"] == "unavailable"
    assert "none could be identified" in asset.quality_evidence
    assert asset.usage_score == 0
    assert asset.metadata_sources["usage"] == "unavailable"


def test_identifiable_datahub_quality_results_are_used():
    asset = enrich_asset_from_aspects(
        baseline_asset(),
        {
            "testResults": SimpleNamespace(
                passing=[],
                failing=[
                    SimpleNamespace(test="urn:li:test:dataset-quality-assertion")
                ],
            )
        },
    )

    assert asset.quality_status == "failing"
    assert asset.metadata_sources["quality"] == "datahub"
    assert asset.quality_evidence == "DataHub reports 1 failing quality test(s)."
