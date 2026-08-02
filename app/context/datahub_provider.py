from __future__ import annotations

import asyncio
from typing import Any

from datahub.sdk.main_client import DataHubClient

from app.context.base import ContextProvider
from app.models import Asset, ChangeRequest, ContextGraph, LineageEdge


class DataHubContextProvider(ContextProvider):
    """Read live downstream dependencies from the connected DataHub instance."""

    name = "datahub"

    def __init__(self) -> None:
        self.client = DataHubClient.from_env()
        self.client.test_connection()

    async def build_context(self, request: ChangeRequest) -> ContextGraph:
        results = await asyncio.to_thread(
            self._fetch_downstream_lineage,
            request.asset_urn,
            request.column,
        )

        root_asset = Asset(
            urn=request.asset_urn,
            name=self._name_from_urn(request.asset_urn),
            asset_type="dataset",
            platform=self._platform_from_urn(request.asset_urn),
            owners=[],
            tags=[],
            criticality="high",
            usage_score=0,
            fields=[request.column],
            quality_status="unknown",
        )

        assets: list[Asset] = [root_asset]
        edges: list[LineageEdge] = []
        seen = {request.asset_urn}

        for result in results[:60]:
            urn = str(getattr(result, "urn", "") or "")
            if not urn or urn in seen:
                continue
            seen.add(urn)

            raw_type = str(getattr(result, "type", "") or "")
            asset_type = self._normalize_asset_type(raw_type)

            platform = self._clean_value(getattr(result, "platform", None))
            if not platform:
                platform = self._platform_from_urn(urn)

            name = self._clean_value(getattr(result, "name", None))
            if not name:
                name = self._name_from_urn(urn)

            hops = int(getattr(result, "hops", 1) or 1)

            assets.append(
                Asset(
                    urn=urn,
                    name=name,
                    asset_type=asset_type,
                    platform=platform or "unknown",
                    owners=[],
                    tags=[],
                    criticality=self._infer_criticality(
                        asset_type=asset_type,
                        platform=platform,
                        hops=hops,
                    ),
                    usage_score=0,
                    fields=[],
                    quality_status="unknown",
                )
            )

            edges.append(
                LineageEdge(
                    source=request.asset_urn,
                    target=urn,
                    via_column=request.column,
                )
            )

        return ContextGraph(
            root_asset=root_asset,
            assets=assets,
            edges=edges,
            glossary_terms=[],
            context_notes=[
                (
                    f"Live DataHub returned {len(assets) - 1} unique downstream "
                    "dependencies within two hops."
                ),
                (
                    "LineageShield first requests column-level lineage and "
                    "automatically falls back to dataset-level lineage when the "
                    "column has no fine-grained lineage."
                ),
                (
                    "Owners, governance tags, usage, and quality assertions are "
                    "the next live-enrichment milestone."
                ),
            ],
        )

    def _fetch_downstream_lineage(
        self,
        source_urn: str,
        source_column: str,
    ) -> list[Any]:
        try:
            column_results = list(
                self.client.lineage.get_lineage(
                    source_urn=source_urn,
                    source_column=source_column,
                    direction="downstream",
                    max_hops=2,
                    count=200,
                )
            )
        except Exception:
            column_results = []

        if column_results:
            return column_results

        return list(
            self.client.lineage.get_lineage(
                source_urn=source_urn,
                direction="downstream",
                max_hops=2,
                count=200,
            )
        )

    @staticmethod
    def _normalize_asset_type(raw_type: str) -> str:
        value = raw_type.lower().replace(" ", "_")

        if "dashboard" in value or "chart" in value:
            return "dashboard"
        if "data_job" in value or "datajob" in value or "flow" in value:
            return "pipeline"
        if "ml" in value or "model" in value:
            return "ml_model"

        return "dataset"

    @staticmethod
    def _infer_criticality(
        *,
        asset_type: str,
        platform: str,
        hops: int,
    ) -> str:
        if asset_type in {"dashboard", "ml_model"}:
            return "critical"

        if asset_type == "pipeline":
            return "high" if hops == 1 else "medium"

        important_platforms = {
            "powerbi",
            "tableau",
            "looker",
            "snowflake",
        }
        if hops == 1 and platform.lower() in important_platforms:
            return "high"

        return "medium"

    @staticmethod
    def _clean_value(value: Any) -> str:
        if value is None:
            return ""

        text = str(value).strip()
        if text.lower() == "none":
            return ""

        if text.startswith("urn:li:dataPlatform:"):
            return text.rsplit(":", 1)[-1]

        return text

    @staticmethod
    def _platform_from_urn(urn: str) -> str:
        marker = "urn:li:dataPlatform:"
        if marker in urn:
            return urn.split(marker, 1)[1].split(",", 1)[0].strip("()")

        if urn.startswith(("urn:li:dashboard:(", "urn:li:chart:(")):
            return urn.split("(", 1)[1].split(",", 1)[0]

        if "urn:li:dataFlow:(" in urn:
            return urn.split("urn:li:dataFlow:(", 1)[1].split(",", 1)[0]

        return "unknown"

    @staticmethod
    def _name_from_urn(urn: str) -> str:
        if urn.startswith("urn:li:dataset:("):
            inner = urn.split("(", 1)[1].rsplit(")", 1)[0]
            parts = inner.split(",")
            if len(parts) >= 3:
                return parts[-2]

        if urn.startswith(("urn:li:dashboard:(", "urn:li:chart:(")):
            inner = urn.split("(", 1)[1].rsplit(")", 1)[0]
            return inner.split(",", 1)[-1]

        if urn.startswith("urn:li:dataJob:("):
            return urn.rsplit(",", 1)[-1].strip("()")

        return urn.rsplit(",", 1)[-1].strip("()")
