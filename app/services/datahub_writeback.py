from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from app.context.datahub_metadata import entity_type_from_urn
from app.models import (
    DataHubMutationPreview,
    WritebackPreview,
    WritebackReceipt,
    WritebackRecord,
)
from app.services.analysis_store import StoredAnalysis


logger = logging.getLogger(__name__)


class WritebackServiceError(Exception):
    status_code = 500
    error_code = "writeback_error"
    mutation_state = "not_started"
    retryable = False

    def as_detail(self) -> dict[str, str | bool]:
        return {
            "code": self.error_code,
            "message": str(self),
            "mutation_state": self.mutation_state,
            "retryable": self.retryable,
        }


class MutationsDisabledError(WritebackServiceError):
    status_code = 403
    error_code = "mutations_disabled"


class UnsupportedWritebackTargetError(WritebackServiceError):
    status_code = 409
    error_code = "unsupported_writeback_target"


class ManagedSectionConflictError(WritebackServiceError):
    status_code = 409
    error_code = "managed_section_conflict"


class DataHubPreviewError(WritebackServiceError):
    status_code = 503
    error_code = "datahub_preview_failed"
    retryable = True


class DataHubPreviewTimeoutError(DataHubPreviewError):
    status_code = 504
    error_code = "datahub_preview_timeout"


class DataHubApplyError(WritebackServiceError):
    status_code = 502
    error_code = "datahub_apply_failed"
    mutation_state = "unknown"
    retryable = True


class DataHubApplyTimeoutError(DataHubApplyError):
    status_code = 504
    error_code = "datahub_apply_timeout"


class DataHubMutationGateway(Protocol):
    def get_description(self, urn: str) -> str: ...

    def patch_description(self, urn: str, description: str) -> None: ...


class SdkDataHubMutationGateway:
    """Small adapter around the installed DataHub SDK's patch-capable entity API."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def get_description(self, urn: str) -> str:
        entity = self._get_client().entities.get(urn)
        value = getattr(entity, "description", None)
        return str(value) if value else ""

    def patch_description(self, urn: str, description: str) -> None:
        try:
            from datahub.emitter.mcp_patch_builder import MetadataPatchProposal
        except ImportError as exc:
            raise RuntimeError(
                "The installed DataHub SDK does not provide metadata patch support."
            ) from exc

        patch = MetadataPatchProposal(urn)
        # EntityClient.update publicly accepts MetadataPatchProposal in SDK 1.6.
        # The generic builder does not expose a description-specific convenience
        # method, so add the one supported scalar JSON Patch operation here.
        patch._add_patch(  # noqa: SLF001 - required by this installed SDK surface
            "editableDatasetProperties",
            "add",
            ("description",),
            description,
        )
        self._get_client().entities.update(patch)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from datahub.sdk.main_client import DataHubClient
        except ImportError as exc:
            raise RuntimeError(
                "The DataHub SDK is not installed. Install requirements-datahub.txt."
            ) from exc
        self._client = DataHubClient.from_env()
        return self._client


class DataHubWritebackService:
    def __init__(
        self,
        *,
        enabled: bool = False,
        gateway: DataHubMutationGateway | None = None,
        timeout_seconds: float = 12.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.enabled = enabled
        self._gateway = gateway or SdkDataHubMutationGateway()
        self._timeout_seconds = timeout_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    async def preview(self, analysis: StoredAnalysis) -> WritebackPreview:
        self._validate_target(analysis)
        managed_section = render_managed_section(analysis.record)
        try:
            existing = await asyncio.wait_for(
                asyncio.to_thread(
                    self._gateway.get_description,
                    analysis.record.root_asset.urn,
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            logger.warning(
                "DataHub write-back preview timed out for analysis %s",
                analysis.record.analysis_id,
            )
            raise DataHubPreviewTimeoutError(
                "DataHub did not return the current root documentation before the timeout."
            ) from exc
        except WritebackServiceError:
            raise
        except Exception as exc:
            logger.warning(
                "DataHub write-back preview failed for analysis %s (%s)",
                analysis.record.analysis_id,
                type(exc).__name__,
            )
            raise DataHubPreviewError(
                "DataHub could not return the current root documentation. No mutation occurred."
            ) from exc

        resulting_description = merge_managed_section(
            existing,
            analysis.record.analysis_id,
            managed_section,
        )
        warnings = [
            "This preview is read-only. No migration SQL will be executed.",
            "Apply re-reads the latest description before patching to preserve concurrent edits.",
        ]
        if not self.enabled:
            warnings.insert(
                0,
                "DataHub mutations are disabled. Restart with DATAHUB_MUTATIONS_ENABLED=true to apply.",
            )
        return WritebackPreview(
            mutations_enabled=self.enabled,
            expires_at=analysis.expires_at,
            record=analysis.record,
            mutation=DataHubMutationPreview(
                managed_section=managed_section,
                resulting_description=resulting_description,
                already_applied=resulting_description == existing,
            ),
            warnings=warnings,
        )

    async def apply(self, analysis: StoredAnalysis) -> WritebackReceipt:
        if not self.enabled:
            raise MutationsDisabledError(
                "DataHub mutations are disabled. Set DATAHUB_MUTATIONS_ENABLED=true and restart LineageShield."
            )
        self._validate_target(analysis)
        managed_section = render_managed_section(analysis.record)

        try:
            existing = await asyncio.wait_for(
                asyncio.to_thread(
                    self._gateway.get_description,
                    analysis.record.root_asset.urn,
                ),
                timeout=self._timeout_seconds,
            )
            resulting_description = merge_managed_section(
                existing,
                analysis.record.analysis_id,
                managed_section,
            )
        except TimeoutError as exc:
            raise DataHubPreviewTimeoutError(
                "DataHub did not return the current root documentation before the timeout. No mutation started."
            ) from exc
        except WritebackServiceError:
            raise
        except Exception as exc:
            logger.warning(
                "DataHub pre-apply read failed for analysis %s (%s)",
                analysis.record.analysis_id,
                type(exc).__name__,
            )
            raise DataHubPreviewError(
                "DataHub could not return the latest root documentation. No mutation started."
            ) from exc

        if resulting_description == existing:
            return self._receipt(analysis.record, status="already_applied")

        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    self._gateway.patch_description,
                    analysis.record.root_asset.urn,
                    resulting_description,
                ),
                timeout=self._timeout_seconds,
            )
            verified_description = await asyncio.wait_for(
                asyncio.to_thread(
                    self._gateway.get_description,
                    analysis.record.root_asset.urn,
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            logger.error(
                "DataHub write-back outcome is unknown after a timeout for analysis %s",
                analysis.record.analysis_id,
            )
            raise DataHubApplyTimeoutError(
                "The DataHub request timed out after mutation began. Its outcome is unknown; inspect the root asset before retrying."
            ) from exc
        except Exception as exc:
            logger.error(
                "DataHub write-back outcome is unknown for analysis %s (%s)",
                analysis.record.analysis_id,
                type(exc).__name__,
            )
            raise DataHubApplyError(
                "DataHub did not confirm the write-back. Its outcome is unknown; inspect the root asset before retrying."
            ) from exc

        if verified_description != resulting_description:
            raise DataHubApplyError(
                "DataHub accepted the request but read-back verification did not match. Inspect the root asset before retrying."
            )
        logger.info(
            "Confirmed DataHub documentation write-back for analysis %s",
            analysis.record.analysis_id,
        )
        return self._receipt(analysis.record, status="applied")

    @staticmethod
    def _validate_target(analysis: StoredAnalysis) -> None:
        if analysis.provider != "datahub":
            raise UnsupportedWritebackTargetError(
                "Write-back is available only for analyses completed with the live DataHub provider."
            )
        if entity_type_from_urn(analysis.record.root_asset.urn) != "dataset":
            raise UnsupportedWritebackTargetError(
                "This write-back version supports reviewed root datasets only."
            )

    def _receipt(
        self,
        record: WritebackRecord,
        *,
        status: Literal["applied", "already_applied"],
    ) -> WritebackReceipt:
        already_applied = status == "already_applied"
        return WritebackReceipt(
            analysis_id=record.analysis_id,
            asset=record.root_asset,
            applied_at=self._now(),
            status=status,
            idempotent=already_applied,
            message=(
                "The same managed section was already present; DataHub was not mutated again."
                if already_applied
                else "DataHub confirmed the LineageShield documentation patch. No migration was executed."
            ),
        )

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def render_managed_section(record: WritebackRecord) -> str:
    change = record.proposed_change
    approvals = ", ".join(_safe_inline(value) for value in record.required_approvals)
    lines = [
        _begin_marker(record.analysis_id),
        "## LineageShield change-impact record",
        "",
        f"- **Analysis ID:** `{_safe_inline(record.analysis_id)}`",
        f"- **Analysis timestamp:** {_safe_inline(record.analysis_timestamp.isoformat())}",
        f"- **Proposed change:** {_safe_inline(change.change_type)}",
        f"- **Affected column:** `{_safe_inline(change.column)}`",
    ]
    if change.new_value:
        lines.append(f"- **New value:** `{_safe_inline(change.new_value)}`")
    lines.extend(
        [
            f"- **Merge decision:** **{_safe_inline(record.decision)}**",
            f"- **Risk:** {record.risk_score}/100 ({_safe_inline(record.risk_level)})",
            f"- **Affected assets:** {record.affected_asset_count}",
            f"- **Required approvals:** {approvals or 'None identified from loaded owner metadata'}",
            f"- **Review rationale:** {_safe_inline(record.rationale)}",
        ]
    )
    if change.reason:
        lines.append(f"- **Proposal rationale:** {_safe_inline(change.reason)}")

    lines.extend(["", "### Deterministic evidence"])
    evidence = record.evidence_summary[:6] or ["No positive risk factors were recorded."]
    lines.extend(f"- {_safe_inline(value)}" for value in evidence)
    lines.extend(
        [
            "",
            "### Generated safeguard summary",
            f"- **Migration:** {_safe_inline(record.migration_summary)}",
            f"- **Rollback:** {_safe_inline(record.rollback_summary)}",
            "",
            "_LineageShield recorded review metadata only. No migration SQL was executed._",
            _end_marker(record.analysis_id),
        ]
    )
    return "\n".join(lines)


def merge_managed_section(
    existing_description: str,
    analysis_id: str,
    managed_section: str,
) -> str:
    existing = existing_description or ""
    begin = _begin_marker(analysis_id)
    end = _end_marker(analysis_id)
    begin_count = existing.count(begin)
    end_count = existing.count(end)

    if begin_count != end_count or begin_count > 1:
        raise ManagedSectionConflictError(
            "The existing LineageShield markers are incomplete or duplicated. Repair the managed section in DataHub before retrying."
        )
    if begin_count == 1:
        pattern = re.compile(
            re.escape(begin) + r".*?" + re.escape(end),
            flags=re.DOTALL,
        )
        return pattern.sub(lambda _: managed_section, existing, count=1)
    if not existing:
        return managed_section
    separator = (
        ""
        if existing.endswith("\n\n")
        else ("\n" if existing.endswith("\n") else "\n\n")
    )
    return f"{existing}{separator}{managed_section}"


def _begin_marker(analysis_id: str) -> str:
    return f"<!-- LINEAGESHIELD:BEGIN {analysis_id} -->"


def _end_marker(analysis_id: str) -> str:
    return f"<!-- LINEAGESHIELD:END {analysis_id} -->"


def _safe_inline(value: object) -> str:
    text = " ".join(str(value).split())
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("`", "'")
    )
