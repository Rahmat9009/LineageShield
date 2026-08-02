from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.context.datahub_provider import DataHubContextProvider
from app.context.demo_provider import DemoContextProvider
from app.models import AnalysisResult, ChangeRequest
from app.services.change_impact import ChangeImpactService


settings = get_settings()
app = FastAPI(
    title="LineageShield API",
    version="0.1.0",
    description="Metadata-aware schema-change impact analysis.",
)

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def build_service() -> ChangeImpactService:
    if settings.context_provider.strip().lower() == "datahub":
        return ChangeImpactService(DataHubContextProvider())
    return ChangeImpactService(DemoContextProvider())


service = build_service()


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "context_provider": service.provider.name,
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
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
