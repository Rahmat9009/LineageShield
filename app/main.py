import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.context.base import ProviderUnavailableError
from app.context.datahub_provider import DataHubContextProvider
from app.context.demo_provider import DemoContextProvider
from app.models import AnalysisResult, ChangeRequest
from app.services.change_impact import ChangeImpactService


logger = logging.getLogger(__name__)
settings = get_settings()
app = FastAPI(
    title="LineageShield API",
    version="0.2.0",
    description="Metadata-aware schema-change impact analysis.",
)

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def build_service() -> ChangeImpactService:
    if settings.context_provider.strip().lower() == "datahub":
        provider = DataHubContextProvider(
            health_timeout_seconds=settings.datahub_health_timeout_seconds,
            lineage_timeout_seconds=settings.datahub_lineage_timeout_seconds,
        )
        return ChangeImpactService(provider)
    return ChangeImpactService(DemoContextProvider())


service = build_service()


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
        return await service.analyze(request)
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
