from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import unquote

from app.models import Asset, AssetOwner, MetadataSummary, MetadataValue


AspectBag = Mapping[str, Any]

ENTITY_API_TYPES = {
    "dataset": "dataset",
    "dashboard": "dashboard",
    "chart": "chart",
    "datajob": "dataJob",
    "dataflow": "dataFlow",
    "mlmodel": "mlModel",
    "mlmodelgroup": "mlModelGroup",
}

NAME_ASPECTS = {
    "dataset": ("datasetProperties", ("name", "qualifiedName")),
    "dashboard": ("dashboardInfo", ("title",)),
    "chart": ("chartInfo", ("title",)),
    "datajob": ("dataJobInfo", ("name",)),
    "dataflow": ("dataFlowInfo", ("name",)),
    "mlmodel": ("mlModelProperties", ("name",)),
    "mlmodelgroup": ("mlModelGroupProperties", ("name",)),
}

DESCRIPTION_ASPECTS = {
    "dataset": ("editableDatasetProperties", "description", "datasetProperties"),
    "dashboard": ("dashboardInfo", "description", None),
    "chart": ("chartInfo", "description", None),
    "datajob": ("editableDataJobProperties", "description", "dataJobInfo"),
    "dataflow": ("dataFlowInfo", "description", None),
    "mlmodel": ("mlModelProperties", "description", None),
    "mlmodelgroup": ("mlModelGroupProperties", "description", None),
}


def entity_type_from_urn(urn: str) -> str:
    parts = urn.split(":", 3)
    return parts[2].lower() if len(parts) > 2 else "unknown"


def entity_api_type(urn: str) -> str | None:
    return ENTITY_API_TYPES.get(entity_type_from_urn(urn))


def normalize_reference_label(urn: str) -> str:
    """Turn a reference URN into a safe readable fallback label."""

    decoded = unquote(str(urn)).strip()
    identifier = decoded.rsplit(":", 1)[-1].strip(" ()[]{}\"'")
    entity_type = entity_type_from_urn(decoded)

    if entity_type == "corpuser" and "@" in identifier:
        local, domain = identifier.split("@", 1)
        tenant_prefix, separator, remaining = local.partition(".")
        if separator and re.fullmatch(r"[a-fA-F0-9-]{6,}", tenant_prefix):
            local = remaining
        return f"{local}@{domain}"

    identifier = identifier.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
    identifier = re.sub(r"^_+default_+", "", identifier, flags=re.IGNORECASE)
    identifier = re.sub(r"^_+system_+", "", identifier, flags=re.IGNORECASE)
    identifier = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", identifier)
    identifier = re.sub(r"[_-]+", " ", identifier)
    identifier = re.sub(r"\s+", " ", identifier).strip()
    if not identifier:
        return "Unnamed reference"
    return " ".join(
        word if word.isupper() and len(word) <= 3 else word.capitalize()
        for word in identifier.split()
    )


def enrich_asset_from_aspects(asset: Asset, aspects: AspectBag) -> Asset:
    """Merge typed DataHub aspects into an asset without inventing values."""

    if not aspects:
        return asset

    updates: dict[str, Any] = {}
    sources = dict(asset.metadata_sources)
    sources["entity"] = "datahub"
    entity_type = entity_type_from_urn(asset.urn)

    name = _entity_name(entity_type, aspects)
    if name:
        updates["name"] = _display_text(name)
        sources["name"] = "datahub"

    platform = _clean_platform(_aspect_attribute(aspects, "dataPlatformInstance", "platform"))
    if platform:
        updates["platform"] = platform
        sources["platform"] = "datahub"

    description = _entity_description(entity_type, aspects)
    if description:
        updates["description"] = description
        sources["description"] = "datahub"

    ownership = _aspect(aspects, "ownership")
    if ownership is not None:
        owner_details: list[AssetOwner] = []
        seen_owner_roles: set[tuple[str, str]] = set()
        for owner in getattr(ownership, "owners", None) or []:
            owner_urn = _clean_text(getattr(owner, "owner", ""))
            ownership_type_urn = _clean_text(getattr(owner, "typeUrn", ""))
            raw_ownership_type = _clean_text(getattr(owner, "type", ""))
            if not owner_urn:
                continue
            role_key = ownership_type_urn or raw_ownership_type
            dedupe_key = (owner_urn, role_key)
            if dedupe_key in seen_owner_roles:
                continue
            seen_owner_roles.add(dedupe_key)
            ownership_type = (
                normalize_reference_label(ownership_type_urn)
                if ownership_type_urn
                else _display_text(raw_ownership_type)
            )
            if ownership_type.lower() == "none":
                ownership_type = ""
            owner_details.append(
                AssetOwner(
                    urn=owner_urn,
                    label=normalize_reference_label(owner_urn),
                    ownership_type=ownership_type or None,
                    ownership_type_urn=ownership_type_urn or None,
                )
            )
        owner_urns = _ordered_unique(detail.urn for detail in owner_details)
        updates["owner_urns"] = owner_urns
        updates["owners"] = [normalize_reference_label(urn) for urn in owner_urns]
        updates["owner_details"] = owner_details
        sources["owners"] = "datahub"
        sources["owner_labels"] = "fallback" if owner_urns else "datahub"
        sources["ownership_types"] = (
            "fallback"
            if any(detail.ownership_type_urn for detail in owner_details)
            else "datahub"
        )

    global_tags = _aspect(aspects, "globalTags")
    if global_tags is not None:
        tag_urns = _ordered_unique(
            _clean_text(getattr(tag, "tag", ""))
            for tag in (getattr(global_tags, "tags", None) or [])
        )
        updates["tag_urns"] = tag_urns
        updates["tags"] = [normalize_reference_label(urn) for urn in tag_urns]
        sources["tags"] = "datahub"
        sources["tag_labels"] = "fallback" if tag_urns else "datahub"

    glossary = _aspect(aspects, "glossaryTerms")
    if glossary is not None:
        term_urns = _ordered_unique(
            _clean_text(getattr(term, "urn", ""))
            for term in (getattr(glossary, "terms", None) or [])
        )
        updates["glossary_term_urns"] = term_urns
        updates["glossary_terms"] = [
            normalize_reference_label(urn) for urn in term_urns
        ]
        sources["glossary_terms"] = "datahub"
        sources["glossary_term_labels"] = "fallback" if term_urns else "datahub"

    schema = _aspect(aspects, "schemaMetadata")
    if schema is not None:
        updates["fields"] = _ordered_unique(
            _clean_text(getattr(field, "fieldPath", ""))
            for field in (getattr(schema, "fields", None) or [])
        )
        sources["fields"] = "datahub"

    structured_properties = _structured_properties(aspects)
    if structured_properties is not None:
        updates["structured_properties"] = structured_properties
        sources["structured_properties"] = "datahub"

    explicit_criticality = _explicit_criticality(aspects, structured_properties)
    if explicit_criticality is not None:
        value, evidence = explicit_criticality
        updates["criticality"] = value
        updates["criticality_source"] = "datahub"
        updates["criticality_evidence"] = evidence
        sources["criticality"] = "datahub"

    quality_status, quality_evidence = _quality_signal(aspects)
    if quality_status != "unknown":
        updates["quality_status"] = quality_status
        updates["quality_evidence"] = quality_evidence
        sources["quality"] = "datahub"
    elif _aspect(aspects, "testResults") is not None:
        updates["quality_evidence"] = quality_evidence
        sources["quality"] = "unavailable"

    # The installed SDK exposes raw usage timeseries, not a canonical 0-100 score.
    # Leave usage_score at zero until a defensible normalized value is available.
    sources.setdefault("usage", "unavailable")
    updates["metadata_sources"] = sources
    return asset.model_copy(update=updates)


def apply_reference_labels(
    asset: Asset,
    *,
    owner_labels: Mapping[str, str],
    ownership_type_labels: Mapping[str, str],
    tag_labels: Mapping[str, str],
    term_labels: Mapping[str, str],
) -> Asset:
    sources = dict(asset.metadata_sources)
    updates: dict[str, Any] = {}

    if asset.owner_urns:
        updates["owners"] = _ordered_unique(
            owner_labels.get(urn) or normalize_reference_label(urn)
            for urn in asset.owner_urns
        )
        sources["owner_labels"] = (
            "datahub" if all(urn in owner_labels for urn in asset.owner_urns) else "fallback"
        )
        updates["owner_details"] = [
            detail.model_copy(
                update={
                    "label": owner_labels.get(detail.urn) or detail.label,
                    "ownership_type": (
                        ownership_type_labels.get(detail.ownership_type_urn)
                        if detail.ownership_type_urn
                        else detail.ownership_type
                    )
                    or detail.ownership_type,
                }
            )
            for detail in asset.owner_details
        ]
        ownership_type_urns = [
            detail.ownership_type_urn
            for detail in asset.owner_details
            if detail.ownership_type_urn
        ]
        if ownership_type_urns:
            sources["ownership_types"] = (
                "datahub"
                if all(urn in ownership_type_labels for urn in ownership_type_urns)
                else "fallback"
            )

    if asset.tag_urns:
        updates["tags"] = _ordered_unique(
            tag_labels.get(urn) or normalize_reference_label(urn)
            for urn in asset.tag_urns
        )
        sources["tag_labels"] = (
            "datahub" if all(urn in tag_labels for urn in asset.tag_urns) else "fallback"
        )

    if asset.glossary_term_urns:
        updates["glossary_terms"] = _ordered_unique(
            term_labels.get(urn) or normalize_reference_label(urn)
            for urn in asset.glossary_term_urns
        )
        sources["glossary_term_labels"] = (
            "datahub"
            if all(urn in term_labels for urn in asset.glossary_term_urns)
            else "fallback"
        )

    updates["metadata_sources"] = sources
    return asset.model_copy(update=updates)


def reference_label(entity_type: str, urn: str, aspects: AspectBag) -> str:
    candidates: tuple[tuple[str, tuple[str, ...]], ...]
    if entity_type == "corpuser":
        candidates = (
            ("corpUserEditableInfo", ("displayName", "email")),
            ("corpUserInfo", ("displayName", "fullName", "email")),
            ("corpUserKey", ("username",)),
        )
    elif entity_type == "corpGroup":
        candidates = (
            ("corpGroupInfo", ("displayName", "email")),
            ("corpGroupKey", ("name",)),
        )
    elif entity_type == "tag":
        candidates = (("tagProperties", ("name",)), ("tagKey", ("name",)))
    elif entity_type == "glossaryTerm":
        candidates = (
            ("glossaryTermInfo", ("name",)),
            ("glossaryTermKey", ("name",)),
        )
    elif entity_type == "ownershipType":
        candidates = (
            ("ownershipTypeInfo", ("name",)),
            ("ownershipTypeKey", ("name",)),
        )
    else:
        candidates = ()

    for aspect_name, attributes in candidates:
        aspect = _aspect(aspects, aspect_name)
        for attribute in attributes:
            value = _clean_text(getattr(aspect, attribute, "")) if aspect else ""
            if value:
                return value
    return normalize_reference_label(urn)


def summarize_metadata(
    assets: Sequence[Asset], *, enrichment_failures: int = 0
) -> MetadataSummary:
    return MetadataSummary(
        total_assets=len(assets),
        datahub_entities_enriched=sum(
            asset.metadata_sources.get("entity") == "datahub" for asset in assets
        ),
        assets_with_owners=sum(
            bool(asset.owners) and asset.metadata_sources.get("owners") == "datahub"
            for asset in assets
        ),
        assets_with_tags=sum(
            bool(asset.tags) and asset.metadata_sources.get("tags") == "datahub"
            for asset in assets
        ),
        assets_with_schema_fields=sum(
            bool(asset.fields) and asset.metadata_sources.get("fields") == "datahub"
            for asset in assets
        ),
        assets_with_glossary_terms=sum(
            bool(asset.glossary_terms)
            and asset.metadata_sources.get("glossary_terms") == "datahub"
            for asset in assets
        ),
        assets_with_quality_signals=sum(
            asset.metadata_sources.get("quality") == "datahub" for asset in assets
        ),
        assets_with_usage_information=sum(
            asset.metadata_sources.get("usage") == "datahub" for asset in assets
        ),
        assets_with_explicit_criticality=sum(
            asset.criticality_source == "datahub" for asset in assets
        ),
        enrichment_failures=enrichment_failures,
    )


def _entity_name(entity_type: str, aspects: AspectBag) -> str:
    definition = NAME_ASPECTS.get(entity_type)
    if not definition:
        return ""
    aspect_name, attributes = definition
    aspect = _aspect(aspects, aspect_name)
    for attribute in attributes:
        value = _clean_text(getattr(aspect, attribute, "")) if aspect else ""
        if value:
            return value
    return ""


def _entity_description(entity_type: str, aspects: AspectBag) -> str:
    definition = DESCRIPTION_ASPECTS.get(entity_type)
    if not definition:
        return ""
    aspect_name, attribute, fallback_aspect_name = definition
    aspect = _aspect(aspects, aspect_name)
    value = _clean_text(getattr(aspect, attribute, "")) if aspect else ""
    if value or not fallback_aspect_name:
        return value
    fallback = _aspect(aspects, fallback_aspect_name)
    return _clean_text(getattr(fallback, attribute, "")) if fallback else ""


def _structured_properties(
    aspects: AspectBag,
) -> dict[str, list[MetadataValue]] | None:
    aspect = _aspect(aspects, "structuredProperties")
    if aspect is None:
        return None

    properties: dict[str, list[MetadataValue]] = {}
    for assignment in getattr(aspect, "properties", None) or []:
        urn = _clean_text(getattr(assignment, "propertyUrn", ""))
        if not urn:
            continue
        values = [
            normalized
            for value in (getattr(assignment, "values", None) or [])
            if (normalized := _metadata_value(value)) is not None
        ]
        properties[urn] = values
    return properties


def _explicit_criticality(
    aspects: AspectBag,
    structured_properties: Mapping[str, Sequence[MetadataValue]] | None,
) -> tuple[str, str] | None:
    for urn, values in (structured_properties or {}).items():
        key = re.sub(r"[^a-z]", "", urn.rsplit(":", 1)[-1].rsplit(".", 1)[-1].lower())
        if key not in {"criticality", "businesscriticality", "datacriticality"}:
            continue
        for raw_value in values:
            value = str(raw_value).strip().lower()
            if value in {"low", "medium", "high", "critical"}:
                return value, f"DataHub structured property {urn} is {value}."

    for aspect_name in (
        "datasetProperties",
        "dashboardInfo",
        "chartInfo",
        "dataJobInfo",
        "dataFlowInfo",
        "mlModelProperties",
    ):
        aspect = _aspect(aspects, aspect_name)
        properties = getattr(aspect, "customProperties", None) if aspect else None
        for key, raw_value in (properties or {}).items():
            normalized_key = re.sub(r"[^a-z]", "", str(key).lower())
            value = str(raw_value).strip().lower()
            if normalized_key == "criticality" and value in {
                "low",
                "medium",
                "high",
                "critical",
            }:
                return value, f"DataHub custom property {key} is {value}."
    return None


def _quality_signal(aspects: AspectBag) -> tuple[str, str]:
    test_results = _aspect(aspects, "testResults")
    if test_results is None:
        return "unknown", "No reliable DataHub quality signal was available."

    failing = [
        result
        for result in (getattr(test_results, "failing", None) or [])
        if _is_quality_test(result)
    ]
    passing = [
        result
        for result in (getattr(test_results, "passing", None) or [])
        if _is_quality_test(result)
    ]
    if failing:
        return "failing", f"DataHub reports {len(failing)} failing quality test(s)."
    if passing:
        return "passing", f"DataHub reports {len(passing)} passing quality test(s)."
    return (
        "unknown",
        "DataHub test results were present, but none could be identified as quality tests.",
    )


def _is_quality_test(result: Any) -> bool:
    test_urn = _clean_text(getattr(result, "test", "")).lower()
    return "quality" in test_urn or "assertion" in test_urn


def _metadata_value(value: Any) -> MetadataValue | None:
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        for key in ("string", "double", "float", "long", "int", "boolean", "date"):
            candidate = value.get(key)
            if isinstance(candidate, (str, int, float, bool)):
                return candidate
        return None
    to_obj = getattr(value, "to_obj", None)
    if callable(to_obj):
        return _metadata_value(to_obj())
    return None


def _aspect(aspects: AspectBag, name: str) -> Any | None:
    value = aspects.get(name)
    if isinstance(value, tuple):
        return value[0] if value else None
    return value


def _aspect_attribute(aspects: AspectBag, aspect_name: str, attribute: str) -> Any:
    aspect = _aspect(aspects, aspect_name)
    return getattr(aspect, attribute, None) if aspect else None


def _clean_platform(value: Any) -> str:
    text = _clean_text(value)
    if text.startswith("urn:li:dataPlatform:"):
        return text.rsplit(":", 1)[-1]
    return text


def _display_text(value: str) -> str:
    text = _clean_text(value)
    if not text:
        return text
    if any(character.isspace() for character in text):
        return text
    candidate = text.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
    candidate = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", candidate)
    candidate = re.sub(r"[_-]+", " ", candidate)
    return " ".join(
        word if word.isupper() and len(word) <= 3 else word.capitalize()
        for word in candidate.split()
    )


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if not text or text.lower() == "none" else text


def _ordered_unique(values: Iterable[Any]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        unique.append(text)
    return unique
