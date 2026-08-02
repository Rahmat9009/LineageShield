from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import unquote

from app.context.base import ContextProvider, ProviderUnavailableError
from app.models import Asset, ChangeRequest, ContextGraph, LineageEdge


logger = logging.getLogger(__name__)


class DataHubContextProvider(ContextProvider):
    """Read live downstream dependencies from the connected DataHub instance."""

    name = "datahub"

    def __init__(
        self,
        client: Any | None = None,
        *,
        health_timeout_seconds: float = 6.0,
        lineage_timeout_seconds: float = 30.0,
    ) -> None:
        self._client = client
        self.health_timeout_seconds = health_timeout_seconds
        self.lineage_timeout_seconds = lineage_timeout_seconds

    async def healthcheck(self) -> tuple[bool, str]:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._test_connection),
                timeout=self.health_timeout_seconds,
            )
        except TimeoutError:
            logger.warning("DataHub health check timed out")
            return False, "Connection check timed out; verify the local DataHub service."
        except ProviderUnavailableError as exc:
            logger.warning("DataHub provider is unavailable (%s)", type(exc).__name__)
            return False, str(exc)
        except Exception as exc:
            logger.warning(
                "DataHub health check failed (%s)",
                type(exc).__name__,
            )
            return False, "Connection failed; verify DataHub is running and configured."

        return True, "Read-only live lineage provider is ready."

    async def build_context(self, request: ChangeRequest) -> ContextGraph:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._test_connection),
                timeout=self.health_timeout_seconds,
            )
            raw_results, lineage_source = await asyncio.wait_for(
                asyncio.to_thread(
                    self._fetch_downstream_lineage,
                    request.asset_urn,
                    request.column,
                ),
                timeout=self.lineage_timeout_seconds,
            )
        except TimeoutError as exc:
            logger.warning(
                "DataHub request timed out for asset type %s",
                self._entity_type_from_urn(request.asset_urn),
            )
            raise ProviderUnavailableError(
                "The live DataHub lineage request timed out. Verify DataHub is "
                "healthy, then retry the investigation."
            ) from exc
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            logger.warning(
                "DataHub lineage request failed for asset type %s (%s)",
                self._entity_type_from_urn(request.asset_urn),
                type(exc).__name__,
            )
            raise ProviderUnavailableError(
                "DataHub could not return live lineage. Verify the local service "
                "and provider configuration, then retry."
            ) from exc

        results = self._deduplicate_lineage_results(raw_results)[:60]
        dependency_label = (
            "Column-level lineage"
            if lineage_source == "column"
            else "Entity-level lineage fallback"
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
            dependency_type="Source asset",
            hops=0,
        )

        assets: list[Asset] = [root_asset]
        edges: list[LineageEdge] = []

        for result in results:
            urn = self._result_urn(result)
            if not urn or urn == request.asset_urn:
                continue

            raw_type = str(getattr(result, "type", "") or "")
            asset_type = self._normalize_asset_type(raw_type)
            platform = self._clean_value(getattr(result, "platform", None))
            if not platform:
                platform = self._platform_from_urn(urn)

            name = self._display_name(getattr(result, "name", None), urn)
            hops = self._safe_hops(getattr(result, "hops", 1))
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
                    dependency_type=dependency_label,
                    hops=hops,
                )
            )
            edges.append(
                LineageEdge(
                    source=request.asset_urn,
                    target=urn,
                    via_column=request.column if lineage_source == "column" else None,
                    dependency_type=lineage_source,
                )
            )

        fallback_note = (
            "Column-level lineage was available for the submitted field."
            if lineage_source == "column"
            else (
                "The submitted field had no fine-grained downstream lineage, so "
                "LineageShield used DataHub entity-level lineage."
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
                fallback_note,
                (
                    "Owners, governance tags, usage, and quality assertions are not "
                    "yet enriched by the live provider."
                ),
            ],
        )

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            from datahub.sdk.main_client import DataHubClient
        except ImportError as exc:
            raise ProviderUnavailableError(
                "The DataHub SDK is not installed. Install requirements-datahub.txt "
                "to use the live provider."
            ) from exc

        # Keep environment-based DataHub configuration as the live integration path.
        self._client = DataHubClient.from_env()
        return self._client

    def _test_connection(self) -> None:
        client = self._get_client()
        test_connection = getattr(client, "test_connection", None)
        if callable(test_connection):
            test_connection()

    def _fetch_downstream_lineage(
        self,
        source_urn: str,
        source_column: str,
    ) -> tuple[list[Any], str]:
        client = self._get_client()
        try:
            column_results = list(
                client.lineage.get_lineage(
                    source_urn=source_urn,
                    source_column=source_column,
                    direction="downstream",
                    max_hops=2,
                    count=200,
                )
            )
        except Exception as exc:
            logger.info(
                "Column-level DataHub lineage was unavailable (%s); using entity fallback",
                type(exc).__name__,
            )
            column_results = []

        if column_results:
            return column_results, "column"

        entity_results = list(
            client.lineage.get_lineage(
                source_urn=source_urn,
                direction="downstream",
                max_hops=2,
                count=200,
            )
        )
        return entity_results, "entity"

    @classmethod
    def _deduplicate_lineage_results(cls, results: list[Any]) -> list[Any]:
        unique: list[Any] = []
        seen: set[str] = set()
        for result in results:
            urn = cls._result_urn(result)
            if not urn or urn in seen:
                continue
            seen.add(urn)
            unique.append(result)
        return unique

    @staticmethod
    def _result_urn(result: Any) -> str:
        return str(getattr(result, "urn", "") or "").strip()

    @staticmethod
    def _safe_hops(value: Any) -> int:
        try:
            return min(10, max(1, int(value or 1)))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _normalize_asset_type(raw_type: str) -> str:
        value = raw_type.lower().replace(" ", "_")
        if "chart" in value:
            return "chart"
        if "dashboard" in value:
            return "dashboard"
        if "data_job" in value or "datajob" in value or "flow" in value:
            return "pipeline"
        if "feature" in value and "table" in value:
            return "feature_table"
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
        if asset_type in {"dashboard", "chart", "ml_model", "feature_table"}:
            return "critical"
        if asset_type == "pipeline":
            return "high" if hops == 1 else "medium"

        important_platforms = {"powerbi", "tableau", "looker", "snowflake"}
        if hops == 1 and platform.lower() in important_platforms:
            return "high"
        return "medium"

    @staticmethod
    def _clean_value(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text or text.lower() == "none":
            return ""
        if text.startswith("urn:li:dataPlatform:"):
            return text.rsplit(":", 1)[-1]
        return text

    @classmethod
    def _display_name(cls, value: Any, urn: str) -> str:
        text = cls._clean_value(value)
        if not text or text.startswith("urn:li:"):
            return cls._name_from_urn(urn)
        if any(character.isspace() for character in text):
            return text
        return cls._humanize_identifier(text)

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

    @classmethod
    def _name_from_urn(cls, urn: str) -> str:
        if "(" not in urn or ")" not in urn:
            return cls._humanize_identifier(urn.rsplit(":", 1)[-1])

        inner = urn.split("(", 1)[1].rsplit(")", 1)[0]
        entity_type = cls._entity_type_from_urn(urn)

        if entity_type == "dataset":
            without_environment = inner.rsplit(",", 1)[0]
            identifier = without_environment.rsplit(",", 1)[-1]
        elif entity_type in {"dataflow", "mlmodel"}:
            identifier = inner.rsplit(",", 1)[0].rsplit(",", 1)[-1]
        else:
            identifier = inner.rsplit(",", 1)[-1]

        return cls._humanize_identifier(identifier)

    @staticmethod
    def _entity_type_from_urn(urn: str) -> str:
        parts = urn.split(":", 3)
        return parts[2].lower() if len(parts) > 2 else "unknown"

    @staticmethod
    def _humanize_identifier(identifier: str) -> str:
        text = unquote(str(identifier)).strip(" ()[]{}\"'")
        text = text.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
        text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
        text = re.sub(r"[_-]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return "Unnamed asset"
        return " ".join(
            word if word.isupper() and len(word) <= 3 else word.capitalize()
            for word in text.split()
        )
