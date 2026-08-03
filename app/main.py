import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.context.base import ProviderUnavailableError
from app.context.datahub_provider import DataHubContextProvider
from app.context.demo_provider import DemoContextProvider
from app.models import (
    AnalysisResult,
    ChangeRequest,
    WritebackApplyRequest,
    WritebackPreview,
    WritebackPreviewRequest,
    WritebackReceipt,
)
from app.services.analysis_store import (
    AnalysisExpiredError,
    AnalysisNotFoundError,
    AnalysisStore,
    StoredAnalysis,
)
from app.services.agent_context import AgentContextService
from app.services.change_impact import ChangeImpactService
from app.services.datahub_writeback import (
    DataHubWritebackService,
    WritebackServiceError,
)


logger = logging.getLogger(__name__)
settings = get_settings()
app = FastAPI(
    title="LineageShield API",
    version="0.4.0",
    description="Metadata-aware schema-change impact analysis.",
)

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def build_service() -> ChangeImpactService:
    if settings.context_provider.strip().lower() == "datahub":
        provider = DataHubContextProvider(
            health_timeout_seconds=settings.datahub_health_timeout_seconds,
            lineage_timeout_seconds=settings.datahub_lineage_timeout_seconds,
            enrichment_timeout_seconds=settings.datahub_enrichment_timeout_seconds,
            enrichment_request_timeout_seconds=(
                settings.datahub_enrichment_request_timeout_seconds
            ),
            enrichment_concurrency=settings.datahub_enrichment_concurrency,
            enrichment_batch_size=settings.datahub_enrichment_batch_size,
        )
        return ChangeImpactService(
            provider,
            agent_investigator=AgentContextService(
                client_factory=provider.get_client,
                total_timeout_seconds=settings.agent_context_timeout_seconds,
                tool_timeout_seconds=settings.agent_context_tool_timeout_seconds,
                max_lineage_results=settings.agent_context_max_lineage_results,
            ),
        )
    return ChangeImpactService(DemoContextProvider())


service = build_service()
analysis_store = AnalysisStore(
    ttl_seconds=settings.analysis_store_ttl_seconds,
    max_entries=settings.analysis_store_max_entries,
)
writeback_service = DataHubWritebackService(
    enabled=settings.datahub_mutations_enabled,
    timeout_seconds=settings.datahub_mutation_timeout_seconds,
)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str | bool]:
    try:
        connected, detail = await service.provider.healthcheck()
    except Exception as exc:
        logger.error(
            "Context provider health check failed unexpectedly (%s)",
            type(exc).__name__,
        )
        connected = False
        detail = "The configured context provider could not be checked."

    return {
        "status": "ok" if connected else "degraded",
        "app": settings.app_name,
        "context_provider": service.provider.name,
        "provider": service.provider.name,
        "connected": connected,
        "detail": detail,
        "mutations_enabled": writeback_service.enabled,
        "writeback_scope": "root-dataset-description",
    }


@app.get("/api/demo-context")
async def demo_context() -> dict:
    provider = DemoContextProvider()
    request = ChangeRequest(
        asset_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,prod.customers,PROD)",
        column="customer_region",
        change_type="rename",
        new_value="sales_region",
    )
    context = await provider.build_context(request)
    return context.model_dump()


@app.post("/api/analyze", response_model=AnalysisResult)
async def analyze(request: ChangeRequest) -> AnalysisResult:
    try:
        result = await service.analyze(request)
        analysis_store.put(request, result)
        return result
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Unexpected impact analysis failure for change type %s (%s)",
            request.change_type,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="The investigation failed unexpectedly. Review server logs and retry.",
        ) from exc


@app.post("/api/writeback/preview", response_model=WritebackPreview)
async def preview_writeback(request: WritebackPreviewRequest) -> WritebackPreview:
    analysis = _stored_analysis(request.analysis_id)
    try:
        return await writeback_service.preview(analysis)
    except WritebackServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from exc


@app.post("/api/writeback/apply", response_model=WritebackReceipt)
async def apply_writeback(request: WritebackApplyRequest) -> WritebackReceipt:
    analysis = _stored_analysis(request.analysis_id)
    try:
        return await writeback_service.apply(analysis)
    except WritebackServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from exc


def _stored_analysis(analysis_id: str) -> StoredAnalysis:
    try:
        return analysis_store.get(analysis_id)
    except AnalysisExpiredError as exc:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "analysis_expired",
                "message": str(exc),
                "mutation_state": "not_started",
                "retryable": False,
            },
        ) from exc
    except AnalysisNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "analysis_not_found",
                "message": str(exc),
                "mutation_state": "not_started",
                "retryable": False,
            },
        ) from exc
