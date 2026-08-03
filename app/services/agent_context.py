from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import metadata
from time import perf_counter
from typing import Any, Protocol

from app.models import (
    AgentEvidenceReference,
    AgentInvestigationTrace,
    AgentToolExecution,
    AgentToolFailure,
    Asset,
    ChangeRequest,
    ContextGraph,
)


logger = logging.getLogger(__name__)


class AgentContextToolkit(Protocol):
    @property
    def version(self) -> str: ...

    def get_entities(self, client: Any, urns: list[str]) -> list[dict[str, Any]]: ...

    def get_lineage(
        self,
        client: Any,
        *,
        urn: str,
        column: str | None,
        max_hops: int,
        max_results: int,
    ) -> dict[str, Any]: ...


class SdkAgentContextToolkit:
    """Adapter around the installed DataHub Agent Context Kit read tools.

    Exposes only the installed read functions to LineageShield. The upstream
    package namespace eagerly imports other tool modules, but this adapter never
    requests or invokes any mutation function or optional model adapter.
    """

    @property
    def version(self) -> str:
        return metadata.version("datahub-agent-context")

    def get_entities(self, client: Any, urns: list[str]) -> list[dict[str, Any]]:
        from datahub_agent_context.context import DataHubContext
        from datahub_agent_context.mcp_tools.entities import get_entities

        with DataHubContext(client):
            return get_entities(urns=urns)

    def get_lineage(
        self,
        client: Any,
        *,
        urn: str,
        column: str | None,
        max_hops: int,
        max_results: int,
    ) -> dict[str, Any]:
        from datahub_agent_context.context import DataHubContext
        from datahub_agent_context.mcp_tools.lineage import get_lineage

        with DataHubContext(client):
            return get_lineage(
                urn=urn,
                column=column,
                upstream=False,
                max_hops=max_hops,
                max_results=max_results,
            )


@dataclass(slots=True)
class _ToolOutcome:
    value: Any | None
    status: str
    duration_ms: int
    error_type: str | None = None


@dataclass(slots=True)
class _TraceState:
    started: float
    toolkit_version: str
    requested: list[str] = field(default_factory=list)
    succeeded: list[str] = field(default_factory=list)
    failures: list[AgentToolFailure] = field(default_factory=list)
    executions: list[AgentToolExecution] = field(default_factory=list)
    references: list[AgentEvidenceReference] = field(default_factory=list)
    fallback_reasons: list[str] = field(default_factory=list)


class AgentContextService:
    """Run a bounded, read-only, key-free Agent Context investigation."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], Any],
        toolkit: AgentContextToolkit | None = None,
        total_timeout_seconds: float = 24.0,
        tool_timeout_seconds: float = 10.0,
        max_lineage_results: int = 60,
    ) -> None:
        self._client_factory = client_factory
        self._toolkit = toolkit
        self._total_timeout_seconds = total_timeout_seconds
        self._tool_timeout_seconds = tool_timeout_seconds
        self._max_lineage_results = max(1, min(max_lineage_results, 100))

    async def investigate(
        self,
        request: ChangeRequest,
        context: ContextGraph,
    ) -> AgentInvestigationTrace:
        started = perf_counter()
        try:
            toolkit = self._toolkit or SdkAgentContextToolkit()
            toolkit_version = toolkit.version
            client = self._client_factory()
        except Exception as exc:
            logger.warning(
                "Agent Context Kit initialization was unavailable (%s)",
                type(exc).__name__,
            )
            return self._unavailable_trace(
                started,
                reason=(
                    "Agent Context Kit could not be initialized; deterministic "
                    "DataHub provider evidence remained authoritative."
                ),
            )

        state = _TraceState(started=started, toolkit_version=toolkit_version)
        deadline = asyncio.get_running_loop().time() + self._total_timeout_seconds
        await self._investigate_root(
            toolkit,
            client,
            request,
            context,
            state,
            deadline,
        )
        lineage_count, lineage_mode = await self._investigate_lineage(
            toolkit,
            client,
            request,
            context,
            state,
            deadline,
        )
        if state.failures:
            state.fallback_reasons.append(
                "One or more context operations failed; deterministic provider "
                "evidence was retained instead."
            )
        return self._complete_trace(
            context,
            state,
            lineage_count=lineage_count,
            lineage_mode=lineage_mode,
        )

    async def _investigate_root(
        self,
        toolkit: AgentContextToolkit,
        client: Any,
        request: ChangeRequest,
        context: ContextGraph,
        state: _TraceState,
        deadline: float,
    ) -> None:
        root_operation = "get_entities.root"
        root_outcome = await self._call_tool(
            toolkit.get_entities,
            client,
            [request.asset_urn],
            operation=root_operation,
            deadline=deadline,
            requested=state.requested,
        )
        if self._entity_result_succeeded(root_outcome.value):
            state.succeeded.append(root_operation)
            state.references.append(
                AgentEvidenceReference(
                    urn=context.root_asset.urn,
                    label=context.root_asset.name,
                    evidence_type="root_entity",
                )
            )
            state.executions.append(
                AgentToolExecution(
                    tool="get_entities",
                    operation=root_operation,
                    status="success",
                    duration_ms=root_outcome.duration_ms,
                    result_summary="Root entity context was retrieved from DataHub.",
                    evidence_references=[context.root_asset.urn],
                )
            )
        else:
            self._record_failure(
                outcome=root_outcome,
                tool="get_entities",
                operation=root_operation,
                message="Agent Context Kit could not retrieve the root entity context.",
                executions=state.executions,
                failures=state.failures,
            )

    async def _investigate_lineage(
        self,
        toolkit: AgentContextToolkit,
        client: Any,
        request: ChangeRequest,
        context: ContextGraph,
        state: _TraceState,
        deadline: float,
    ) -> tuple[int, str]:
        column_operation = "get_lineage.column_downstream"
        column_outcome = await self._call_tool(
            toolkit.get_lineage,
            client,
            urn=request.asset_urn,
            column=request.column,
            max_hops=2,
            max_results=self._max_lineage_results,
            operation=column_operation,
            deadline=deadline,
            requested=state.requested,
        )
        column_valid, column_count, column_urns = self._lineage_result(
            column_outcome.value
        )
        if column_valid:
            state.succeeded.append(column_operation)
            state.executions.append(
                AgentToolExecution(
                    tool="get_lineage",
                    operation=column_operation,
                    status="success",
                    duration_ms=column_outcome.duration_ms,
                    result_summary=(
                        f"Column-level downstream lineage returned {column_count} "
                        "asset reference(s)."
                    ),
                    evidence_references=column_urns,
                )
            )
            state.references.extend(
                self._evidence_references(
                    column_urns,
                    context.assets,
                    evidence_type="column_lineage",
                )
            )
        else:
            self._record_failure(
                outcome=column_outcome,
                tool="get_lineage",
                operation=column_operation,
                message="Agent Context Kit could not complete column-level lineage.",
                executions=state.executions,
                failures=state.failures,
            )

        lineage_count = column_count if column_valid else 0
        lineage_mode = "column-level lineage"
        needs_dataset_fallback = not column_valid or column_count == 0
        if needs_dataset_fallback:
            state.fallback_reasons.append(
                "Column-level Agent Context Kit lineage returned no usable "
                "downstream evidence; dataset-level lineage was requested."
            )
            dataset_operation = "get_lineage.dataset_downstream"
            dataset_outcome = await self._call_tool(
                toolkit.get_lineage,
                client,
                urn=request.asset_urn,
                column=None,
                max_hops=2,
                max_results=self._max_lineage_results,
                operation=dataset_operation,
                deadline=deadline,
                requested=state.requested,
            )
            dataset_valid, dataset_count, dataset_urns = self._lineage_result(
                dataset_outcome.value
            )
            if dataset_valid:
                state.succeeded.append(dataset_operation)
                lineage_count = dataset_count
                lineage_mode = "dataset-level fallback lineage"
                state.executions.append(
                    AgentToolExecution(
                        tool="get_lineage",
                        operation=dataset_operation,
                        status="success",
                        duration_ms=dataset_outcome.duration_ms,
                        result_summary=(
                            f"Dataset-level downstream lineage returned "
                            f"{dataset_count} asset reference(s)."
                        ),
                        evidence_references=dataset_urns,
                    )
                )
                state.references.extend(
                    self._evidence_references(
                        dataset_urns,
                        context.assets,
                        evidence_type="dataset_lineage",
                    )
                )
            else:
                self._record_failure(
                    outcome=dataset_outcome,
                    tool="get_lineage",
                    operation=dataset_operation,
                    message="Agent Context Kit could not complete dataset-level lineage fallback.",
                    executions=state.executions,
                    failures=state.failures,
                )
        return lineage_count, lineage_mode

    def _complete_trace(
        self,
        context: ContextGraph,
        state: _TraceState,
        *,
        lineage_count: int,
        lineage_mode: str,
    ) -> AgentInvestigationTrace:
        status = "completed"
        if state.failures:
            status = "degraded" if state.succeeded else "unavailable"

        platform_count = len(
            {asset.platform for asset in context.assets if asset.platform}
        )
        narrative = (
            f"The read-only Agent Context Kit workflow resolved context for "
            f"{context.root_asset.name} and returned {lineage_count} downstream "
            f"reference(s) through {lineage_mode}. The authoritative DataHub "
            f"provider independently normalized {max(0, len(context.assets) - 1)} "
            f"unique downstream asset(s) across {platform_count} platform(s). "
            "LineageShield's deterministic policy alone calculates the risk score "
            "and merge decision."
        )
        return AgentInvestigationTrace(
            status=status,
            executed=bool(state.requested),
            toolkit_version=state.toolkit_version,
            narrative_source="deterministic_orchestration",
            tools_requested=state.requested,
            tools_succeeded=state.succeeded,
            tool_failures=state.failures,
            executions=state.executions,
            fallback_occurred=bool(state.fallback_reasons),
            fallback_reason=" ".join(state.fallback_reasons) or None,
            duration_ms=self._duration_ms(state.started),
            context_evidence_references=self._dedupe_references(state.references),
            narrative=narrative,
            limitations=[
                "No LLM or paid model API was called; the narrative is deterministic.",
                "Agent Context Kit evidence cannot alter risk points, approvals, decisions, or mutations.",
                "Timed-out synchronous SDK work may finish in its worker thread after LineageShield stops awaiting it.",
            ],
        )

    async def _call_tool(
        self,
        function: Callable[..., Any],
        *args: Any,
        operation: str,
        deadline: float,
        requested: list[str],
        **kwargs: Any,
    ) -> _ToolOutcome:
        requested.append(operation)
        started = perf_counter()
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return _ToolOutcome(
                value=None,
                status="timeout",
                duration_ms=self._duration_ms(started),
                error_type="total_timeout",
            )

        try:
            value = await asyncio.wait_for(
                asyncio.to_thread(function, *args, **kwargs),
                timeout=min(self._tool_timeout_seconds, remaining),
            )
            return _ToolOutcome(
                value=value,
                status="success",
                duration_ms=self._duration_ms(started),
            )
        except TimeoutError:
            logger.warning("Agent Context Kit operation %s timed out", operation)
            return _ToolOutcome(
                value=None,
                status="timeout",
                duration_ms=self._duration_ms(started),
                error_type="timeout",
            )
        except Exception as exc:
            logger.warning(
                "Agent Context Kit operation %s failed (%s)",
                operation,
                type(exc).__name__,
            )
            return _ToolOutcome(
                value=None,
                status="failure",
                duration_ms=self._duration_ms(started),
                error_type=type(exc).__name__,
            )

    @staticmethod
    def _entity_result_succeeded(value: Any) -> bool:
        return bool(
            isinstance(value, Sequence)
            and not isinstance(value, (str, bytes))
            and any(isinstance(item, Mapping) and "error" not in item for item in value)
        )

    @classmethod
    def _lineage_result(cls, value: Any) -> tuple[bool, int, list[str]]:
        if not isinstance(value, Mapping):
            return False, 0, []
        downstream = value.get("downstreams")
        if not isinstance(downstream, Mapping):
            return False, 0, []
        raw_results = downstream.get("searchResults") or []
        if not isinstance(raw_results, Sequence) or isinstance(raw_results, (str, bytes)):
            return False, 0, []
        urns: list[str] = []
        for item in raw_results:
            if not isinstance(item, Mapping):
                continue
            entity = item.get("entity")
            if not isinstance(entity, Mapping):
                entity = item
            urn = str(entity.get("urn") or "").strip()
            if urn:
                urns.append(urn)
        count = downstream.get("returned")
        if not isinstance(count, int):
            count = len(raw_results)
        return True, max(0, count), cls._unique(urns)

    @staticmethod
    def _record_failure(
        *,
        outcome: _ToolOutcome,
        tool: str,
        operation: str,
        message: str,
        executions: list[AgentToolExecution],
        failures: list[AgentToolFailure],
    ) -> None:
        timed_out = outcome.status == "timeout"
        error_type = outcome.error_type or "invalid_tool_result"
        status = "timeout" if timed_out else "failure"
        executions.append(
            AgentToolExecution(
                tool=tool,
                operation=operation,
                status=status,
                duration_ms=outcome.duration_ms,
                result_summary=message,
            )
        )
        failures.append(
            AgentToolFailure(
                tool=tool,
                operation=operation,
                error_type=error_type,
                message=message,
                timed_out=timed_out,
            )
        )

    @classmethod
    def _evidence_references(
        cls,
        urns: Sequence[str],
        assets: Sequence[Asset],
        *,
        evidence_type: str,
    ) -> list[AgentEvidenceReference]:
        assets_by_urn = {asset.urn: asset for asset in assets}
        return [
            AgentEvidenceReference(
                urn=urn,
                label=assets_by_urn[urn].name if urn in assets_by_urn else "DataHub asset",
                evidence_type=evidence_type,
            )
            for urn in cls._unique(urns)
        ]

    @staticmethod
    def _dedupe_references(
        references: Sequence[AgentEvidenceReference],
    ) -> list[AgentEvidenceReference]:
        unique: list[AgentEvidenceReference] = []
        seen: set[tuple[str, str]] = set()
        for reference in references:
            key = (reference.urn, reference.evidence_type)
            if key in seen:
                continue
            seen.add(key)
            unique.append(reference)
        return unique

    @staticmethod
    def _unique(values: Sequence[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))

    @classmethod
    def _unavailable_trace(
        cls,
        started: float,
        *,
        reason: str,
    ) -> AgentInvestigationTrace:
        return AgentInvestigationTrace(
            status="unavailable",
            executed=False,
            fallback_occurred=True,
            fallback_reason=reason,
            duration_ms=cls._duration_ms(started),
            narrative_source="unavailable",
            narrative=(
                "Agent Context Kit did not execute. LineageShield completed the "
                "investigation using deterministic DataHub provider evidence."
            ),
            limitations=[
                "No Agent Context Kit evidence was added to this analysis.",
                "No LLM, paid model API, or mutation tool was invoked.",
            ],
        )

    @staticmethod
    def _duration_ms(started: float) -> int:
        return max(0, round((perf_counter() - started) * 1_000))
