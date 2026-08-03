from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock

from app.models import (
    AnalysisResult,
    ChangeRequest,
    ProposedChangeRecord,
    WritebackRecord,
    WritebackTarget,
)


class AnalysisStoreError(Exception):
    """Base error for completed-analysis lookup failures."""


class AnalysisNotFoundError(AnalysisStoreError):
    pass


class AnalysisExpiredError(AnalysisStoreError):
    pass


@dataclass(frozen=True, slots=True)
class StoredAnalysis:
    provider: str
    record: WritebackRecord
    expires_at: datetime


class AnalysisStore:
    """Bounded, process-local storage for write-back-safe analysis snapshots.

    This intentionally stores a compact immutable record instead of the complete
    lineage response. It is suitable for a hackathon demo, not durable audit
    persistence or a multi-process deployment.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 1_800,
        max_entries: int = 100,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_entries = max_entries
        self._clock = clock or (lambda: datetime.now(UTC))
        self._entries: OrderedDict[str, StoredAnalysis] = OrderedDict()
        self._lock = RLock()

    def put(self, request: ChangeRequest, result: AnalysisResult) -> StoredAnalysis:
        completed_at = self._now()
        entry = StoredAnalysis(
            provider=result.provider,
            record=self._build_record(request, result, completed_at),
            expires_at=completed_at + self._ttl,
        )
        with self._lock:
            self._prune_expired(completed_at)
            self._entries.pop(result.analysis_id, None)
            self._entries[result.analysis_id] = entry
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return entry

    def get(self, analysis_id: str) -> StoredAnalysis:
        now = self._now()
        with self._lock:
            entry = self._entries.get(analysis_id)
            if entry is not None and entry.expires_at <= now:
                del self._entries[analysis_id]
                raise AnalysisExpiredError(
                    "The completed analysis has expired. Run the investigation again."
                )
            self._prune_expired(now)
            if entry is None:
                raise AnalysisNotFoundError(
                    "The analysis ID is unknown. Run a new investigation in this server process."
                )
            self._entries.move_to_end(analysis_id)
            return entry

    def __len__(self) -> int:
        with self._lock:
            self._prune_expired(self._now())
            return len(self._entries)

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    def _prune_expired(self, now: datetime) -> None:
        expired = [
            analysis_id
            for analysis_id, entry in self._entries.items()
            if entry.expires_at <= now
        ]
        for analysis_id in expired:
            del self._entries[analysis_id]

    @staticmethod
    def _build_record(
        request: ChangeRequest,
        result: AnalysisResult,
        completed_at: datetime,
    ) -> WritebackRecord:
        return WritebackRecord(
            analysis_id=result.analysis_id,
            analysis_timestamp=completed_at,
            root_asset=WritebackTarget(
                urn=result.root_asset.urn,
                name=result.root_asset.name,
                platform=result.root_asset.platform,
            ),
            proposed_change=ProposedChangeRecord(
                change_type=request.change_type,
                column=request.column,
                new_value=request.new_value,
                reason=request.reason,
            ),
            decision=result.decision,
            risk_score=result.risk_score,
            risk_level=result.risk_level,
            affected_asset_count=len(result.affected_assets),
            required_approvals=list(dict.fromkeys(result.required_approvals)),
            rationale=result.explanation,
            evidence_summary=[
                f"+{factor.points} {factor.label}: {factor.evidence}"
                for factor in result.factors
            ],
            migration_summary=_migration_summary(result.artifacts.migration_sql),
            rollback_summary=_rollback_summary(result.artifacts.rollback_plan),
        )


def _migration_summary(migration_sql: str) -> str:
    statements = [
        line.strip()
        for line in migration_sql.splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    ]
    if not statements:
        return "A migration safeguard was generated for human review."
    return _truncate(
        f"First generated migration step (not executed): {statements[0]}",
        400,
    )


def _rollback_summary(steps: list[str]) -> str:
    if not steps:
        return "No rollback steps were generated."
    return _truncate("; ".join(steps), 600)


def _truncate(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1].rstrip()}…"
