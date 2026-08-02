import json
from pathlib import Path

from app.context.base import ContextProvider
from app.models import Asset, ChangeRequest, ContextGraph, LineageEdge


class DemoContextProvider(ContextProvider):
    name = "demo"

    def __init__(self) -> None:
        path = Path(__file__).resolve().parent.parent / "data" / "demo_graph.json"
        self._raw = json.loads(path.read_text(encoding="utf-8"))

    async def build_context(self, request: ChangeRequest) -> ContextGraph:
        assets = [Asset(**asset) for asset in self._raw["assets"]]
        asset_map = {asset.urn: asset for asset in assets}

        root = asset_map.get(request.asset_urn, assets[0])
        relevant_urns = {root.urn}
        frontier = {root.urn}
        all_edges = [LineageEdge(**edge) for edge in self._raw["edges"]]
        selected_edges: list[LineageEdge] = []

        for _ in range(3):
            next_frontier: set[str] = set()
            for edge in all_edges:
                column_matches = edge.via_column in {None, request.column}
                if edge.source in frontier and column_matches:
                    selected_edges.append(edge)
                    relevant_urns.add(edge.target)
                    next_frontier.add(edge.target)
            frontier = next_frontier
            if not frontier:
                break

        affected = [asset_map[urn] for urn in relevant_urns if urn in asset_map]

        return ContextGraph(
            root_asset=root,
            assets=affected,
            edges=selected_edges,
            glossary_terms=self._raw.get("glossary_terms", []),
            context_notes=self._raw.get("context_notes", []),
        )
