from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import unquote

from app.context.base import ContextProvider, ProviderUnavailableError
from app.context.datahub_metadata import (
    apply_reference_labels,
    enrich_asset_from_aspects,
    entity_api_type,
    entity_type_from_urn,
    reference_label,
    summarize_metadata,
)
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
        enrichment_timeout_seconds: float = 20.0,
        enrichment_request_timeout_seconds: float = 6.0,
        enrichment_concurrency: int = 4,
        enrichment_batch_size: int = 50,
    ) -> None:
        self._client = client
        self.health_timeout_seconds = health_timeout_seconds
        self.lineage_timeout_seconds = lineage_timeout_seconds
        self.enrichment_timeout_seconds = enrichment_timeout_seconds
        self.enrichment_request_timeout_seconds = enrichment_request_timeout_seconds
        self.enrichment_concurrency = max(1, enrichment_concurrency)
        self.enrichment_batch_size = max(1, enrichment_batch_size)

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

        return True, "Live lineage provider is ready; analysis remains read-only."

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
            criticality="high",
            criticality_source="inferred",
            criticality_evidence=(
                "Deterministic fallback: source datasets are treated as high impact "
                "for schema-change review; this is not stored DataHub criticality."
            ),
            usage_score=0,
            fields=[request.column],
            quality_status="unknown",
            metadata_sources={
                "name": "fallback",
                "platform": "fallback",
                "owners": "unavailable",
                "tags": "unavailable",
                "glossary_terms": "unavailable",
                "fields": "fallback",
                "quality": "unavailable",
                "usage": "unavailable",
                "criticality": "inferred",
            },
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
            platform_source = "lineage" if platform else "fallback"
            if not platform:
                platform = self._platform_from_urn(urn)

            lineage_name = self._clean_value(getattr(result, "name", None))
            name_source = (
                "lineage"
                if lineage_name and not lineage_name.startswith("urn:li:")
                else "fallback"
            )
            name = self._display_name(lineage_name, urn)
            hops = self._safe_hops(getattr(result, "hops", 1))
            criticality = self._infer_criticality(
                asset_type=asset_type,
                platform=platform,
                hops=hops,
            )
            assets.append(
                Asset(
                    urn=urn,
                    name=name,
                    asset_type=asset_type,
                    platform=platform or "unknown",
                    criticality=criticality,
                    criticality_source="inferred",
                    criticality_evidence=(
                        "Deterministic fallback from asset type, platform, and "
                        f"lineage distance ({hops} hop(s)); this is not stored "
                        "DataHub criticality."
                    ),
                    usage_score=0,
                    quality_status="unknown",
                    metadata_sources={
                        "name": name_source,
                        "platform": platform_source,
                        "owners": "unavailable",
                        "tags": "unavailable",
                        "glossary_terms": "unavailable",
                        "fields": "unavailable",
                        "quality": "unavailable",
                        "usage": "unavailable",
                        "criticality": "inferred",
                    },
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

        enriched_assets, enrichment_failures = await self._enrich_assets(assets)
        root_asset = enriched_assets[0]
        assets = enriched_assets
        metadata_summary = summarize_metadata(
            assets,
            enrichment_failures=enrichment_failures,
        )
        glossary_terms = self._unique_values(
            term for asset in assets for term in asset.glossary_terms
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
            glossary_terms=glossary_terms,
            metadata_summary=metadata_summary,
            context_notes=[
                (
                    f"Live DataHub returned {len(assets) - 1} unique downstream "
                    "dependencies within two hops."
                ),
                fallback_note,
                (
                    f"DataHub entity metadata enriched "
                    f"{metadata_summary.datahub_entities_enriched}/"
                    f"{metadata_summary.total_assets} assets; owners were present on "
                    f"{metadata_summary.assets_with_owners}, tags on "
                    f"{metadata_summary.assets_with_tags}, schema fields on "
                    f"{metadata_summary.assets_with_schema_fields}, and glossary "
                    f"terms on {metadata_summary.assets_with_glossary_terms}."
                ),
                (
                    "Quality is populated only from identifiable DataHub quality test "
                    "results. Usage remains 0 because the installed SDK and connected "
                    "instance did not provide a trustworthy normalized usage score."
                ),
                (
                    f"{enrichment_failures} metadata lookup(s) failed, timed out, or "
                    "returned no entity; safe per-asset fallbacks were preserved."
                    if enrichment_failures
                    else "All requested metadata lookups completed without an isolated failure."
                ),
            ],
        )

    async def _enrich_assets(self, assets: list[Asset]) -> tuple[list[Asset], int]:
        """Enrich assets in bounded batches without making lineage depend on it."""

        client = self._get_client()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.enrichment_timeout_seconds
        semaphore = asyncio.Semaphore(self.enrichment_concurrency)
        graph = getattr(client, "_graph", None) or getattr(client, "graph", None)
        batch_get = getattr(graph, "get_entities", None)

        primary_aspects: dict[str, Mapping[str, Any]] = {}
        failures = 0
        if callable(batch_get):
            groups: dict[str, list[str]] = defaultdict(list)
            for asset in assets:
                api_type = entity_api_type(asset.urn)
                if api_type:
                    groups[api_type].append(asset.urn)
            primary_aspects, failures = await self._fetch_grouped_batches(
                batch_get,
                groups,
                semaphore=semaphore,
                deadline=deadline,
            )
        else:
            entity_client = getattr(client, "entities", None)
            entity_get = getattr(entity_client, "get", None)
            if callable(entity_get):
                primary_aspects, failures = await self._fetch_individual_entities(
                    entity_get,
                    [asset.urn for asset in assets if entity_api_type(asset.urn)],
                    semaphore=semaphore,
                    deadline=deadline,
                )

        enriched = [
            enrich_asset_from_aspects(asset, primary_aspects.get(asset.urn, {}))
            for asset in assets
        ]

        # The public EntityClient does not support users, groups, or tags. Resolve
        # those labels through the same typed bulk API when it is available.
        if not callable(batch_get):
            return enriched, failures

        reference_groups: dict[str, list[str]] = defaultdict(list)
        reference_api_types = {
            "corpuser": "corpuser",
            "corpgroup": "corpGroup",
            "ownershiptype": "ownershipType",
            "tag": "tag",
            "glossaryterm": "glossaryTerm",
        }
        for asset in enriched:
            for urn in (
                *asset.owner_urns,
                *(
                    detail.ownership_type_urn
                    for detail in asset.owner_details
                    if detail.ownership_type_urn
                ),
                *asset.tag_urns,
                *asset.glossary_term_urns,
            ):
                api_type = reference_api_types.get(entity_type_from_urn(urn))
                if api_type:
                    reference_groups[api_type].append(urn)

        reference_aspects, reference_failures = await self._fetch_grouped_batches(
            batch_get,
            reference_groups,
            semaphore=semaphore,
            deadline=deadline,
        )
        failures += reference_failures

        reference_type_by_urn = {
            urn: api_type
            for api_type, urns in reference_groups.items()
            for urn in urns
        }
        labels = {
            urn: reference_label(reference_type_by_urn[urn], urn, aspects)
            for urn, aspects in reference_aspects.items()
            if urn in reference_type_by_urn
        }
        owner_labels = {
            urn: label
            for urn, label in labels.items()
            if entity_type_from_urn(urn) in {"corpuser", "corpgroup"}
        }
        tag_labels = {
            urn: label
            for urn, label in labels.items()
            if entity_type_from_urn(urn) == "tag"
        }
        ownership_type_labels = {
            urn: label
            for urn, label in labels.items()
            if entity_type_from_urn(urn) == "ownershiptype"
        }
        term_labels = {
            urn: label
            for urn, label in labels.items()
            if entity_type_from_urn(urn) == "glossaryterm"
        }
        return (
            [
                apply_reference_labels(
                    asset,
                    owner_labels=owner_labels,
                    ownership_type_labels=ownership_type_labels,
                    tag_labels=tag_labels,
                    term_labels=term_labels,
                )
                for asset in enriched
            ],
            failures,
        )

    async def _fetch_grouped_batches(
        self,
        batch_get: Callable[..., Mapping[str, Any]],
        groups: Mapping[str, Sequence[str]],
        *,
        semaphore: asyncio.Semaphore,
        deadline: float,
    ) -> tuple[dict[str, Mapping[str, Any]], int]:
        task_specs: dict[asyncio.Task, tuple[str, list[str]]] = {}
        for entity_type, raw_urns in groups.items():
            urns = self._unique_values(raw_urns)
            for offset in range(0, len(urns), self.enrichment_batch_size):
                chunk = urns[offset : offset + self.enrichment_batch_size]
                task = asyncio.create_task(
                    self._fetch_batch_resilient(
                        batch_get,
                        entity_type,
                        chunk,
                        semaphore=semaphore,
                    )
                )
                task_specs[task] = (entity_type, chunk)

        if not task_specs:
            return {}, 0

        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        if not remaining:
            for task in task_specs:
                task.cancel()
            await asyncio.gather(*task_specs, return_exceptions=True)
            return {}, sum(len(urns) for _, urns in task_specs.values())

        done, pending = await asyncio.wait(task_specs, timeout=remaining)
        records: dict[str, Mapping[str, Any]] = {}
        failures = sum(len(task_specs[task][1]) for task in pending)
        for task in pending:
            task.cancel()
        if pending:
            logger.warning(
                "DataHub metadata enrichment deadline reached with %d batch(es) pending",
                len(pending),
            )
            await asyncio.gather(*pending, return_exceptions=True)

        for task in done:
            try:
                task_records, task_failures = task.result()
            except Exception as exc:  # Defensive: each worker normally contains failures.
                entity_type, urns = task_specs[task]
                logger.warning(
                    "DataHub %s metadata batch failed unexpectedly for %d item(s) (%s)",
                    entity_type,
                    len(urns),
                    type(exc).__name__,
                )
                failures += len(urns)
                continue
            records.update(task_records)
            failures += len(task_failures)
        return records, failures

    async def _fetch_batch_resilient(
        self,
        batch_get: Callable[..., Mapping[str, Any]],
        entity_type: str,
        urns: list[str],
        *,
        semaphore: asyncio.Semaphore,
    ) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
        try:
            async with semaphore:
                raw = await asyncio.wait_for(
                    asyncio.to_thread(batch_get, entity_type, urns),
                    timeout=self.enrichment_request_timeout_seconds,
                )
            if not isinstance(raw, Mapping):
                raise TypeError("DataHub batch response was not a mapping")
            records = {
                str(urn): aspects
                for urn, aspects in raw.items()
                if str(urn) in urns and isinstance(aspects, Mapping)
            }
            return records, set(urns) - set(records)
        except TimeoutError:
            logger.warning(
                "DataHub %s metadata batch timed out for %d item(s)",
                entity_type,
                len(urns),
            )
            return {}, set(urns)
        except Exception as exc:
            logger.warning(
                "DataHub %s metadata batch failed for %d item(s) (%s)",
                entity_type,
                len(urns),
                type(exc).__name__,
            )
            if len(urns) <= 1:
                return {}, set(urns)
            midpoint = len(urns) // 2
            left, right = await asyncio.gather(
                self._fetch_batch_resilient(
                    batch_get,
                    entity_type,
                    urns[:midpoint],
                    semaphore=semaphore,
                ),
                self._fetch_batch_resilient(
                    batch_get,
                    entity_type,
                    urns[midpoint:],
                    semaphore=semaphore,
                ),
            )
            return ({**left[0], **right[0]}, left[1] | right[1])

    async def _fetch_individual_entities(
        self,
        entity_get: Callable[[str], Any],
        urns: Sequence[str],
        *,
        semaphore: asyncio.Semaphore,
        deadline: float,
    ) -> tuple[dict[str, Mapping[str, Any]], int]:
        async def fetch(urn: str) -> tuple[str, Mapping[str, Any] | None]:
            try:
                async with semaphore:
                    entity = await asyncio.wait_for(
                        asyncio.to_thread(entity_get, urn),
                        timeout=self.enrichment_request_timeout_seconds,
                    )
                aspects = getattr(entity, "_aspects", None)
                return urn, aspects if isinstance(aspects, Mapping) else None
            except Exception as exc:
                logger.warning(
                    "DataHub entity metadata lookup failed for type %s (%s)",
                    self._entity_type_from_urn(urn),
                    type(exc).__name__,
                )
                return urn, None

        unique_urns = self._unique_values(urns)
        tasks = {asyncio.create_task(fetch(urn)): urn for urn in unique_urns}
        if not tasks:
            return {}, 0
        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        done, pending = await asyncio.wait(tasks, timeout=remaining)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        records: dict[str, Mapping[str, Any]] = {}
        failures = len(pending)
        for task in done:
            urn, aspects = task.result()
            if aspects is None:
                failures += 1
            else:
                records[urn] = aspects
        return records, failures

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

    def get_client(self) -> Any:
        """Return the configured SDK client for isolated read-only integrations."""

        return self._get_client()

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

    @staticmethod
    def _unique_values(values: Iterable[Any]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for raw_value in values:
            value = str(raw_value or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            unique.append(value)
        return unique
