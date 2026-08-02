import json
from pathlib import Path

from app.context.base import ContextProvider
from app.models import Asset, ChangeRequest, ContextGraph, LineageEdge, MetadataSummary


class DemoContextProvider(ContextProvider):
    name = "demo"

    def __init__(self) -> None:
        path = Path(__file__).resolve().parent.parent / "data" / "demo_graph.json"
        self._raw = json.loads(path.read_text(encoding="utf-8"))

    async def build_context(self, request: ChangeRequest) -> ContextGraph:
        assets = [
            Asset(**asset).model_copy(
                update={
                    "criticality_source": "demo",
                    "criticality_evidence": "Bundled demo metadata; not read from DataHub.",
                    "usage_evidence": "Bundled demo metadata; not read from DataHub.",
                    "quality_evidence": "Bundled demo metadata; not read from DataHub.",
                    "metadata_sources": {
                        "name": "demo",
                        "platform": "demo",
                        "owners": "demo",
                        "tags": "demo",
                        "glossary_terms": "demo",
                        "fields": "demo",
                        "quality": "demo",
                        "usage": "demo",
                        "criticality": "demo",
                    },
                }
            )
            for asset in self._raw["assets"]
        ]
        asset_map = {asset.urn: asset for asset in assets}

        source = asset_map.get(request.asset_urn, assets[0])
        root = source.model_copy(
            update={"dependency_type": "Source asset", "hops": 0}
        )
        relevant_urns = {root.urn}
        frontier = {root.urn}
        hop_by_urn = {root.urn: 0}
        all_edges = [LineageEdge(**edge) for edge in self._raw["edges"]]
        selected_edges: list[LineageEdge] = []

        for depth in range(1, 4):
            next_frontier: set[str] = set()
            for edge in all_edges:
                column_matches = edge.via_column in {None, request.column}
                if edge.source in frontier and column_matches:
                    selected_edges.append(edge)
                    relevant_urns.add(edge.target)
                    next_frontier.add(edge.target)
                    hop_by_urn.setdefault(edge.target, depth)
            frontier = next_frontier
            if not frontier:
                break

        affected = [
            asset_map[urn].model_copy(
                update={
                    "dependency_type": (
                        "Source asset"
                        if urn == root.urn
                        else "Column-level demo lineage"
                    ),
                    "hops": hop_by_urn.get(urn, 1),
                }
            )
            for urn in relevant_urns
            if urn in asset_map
        ]

        return ContextGraph(
            root_asset=root,
            assets=affected,
            edges=selected_edges,
            glossary_terms=self._raw.get("glossary_terms", []),
            metadata_summary=MetadataSummary(total_assets=len(affected)),
            context_notes=self._raw.get("context_notes", []),
        )

    async def healthcheck(self) -> tuple[bool, str]:
        return True, "Bundled demo metadata is ready; live DataHub is not in use."
