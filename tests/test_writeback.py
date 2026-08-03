from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.context.base import ContextProvider
from app.models import (
    AnalysisResult,
    Asset,
    ChangeRequest,
    ContextGraph,
    GeneratedArtifacts,
    RiskFactor,
)
from app.services.analysis_store import (
    AnalysisExpiredError,
    AnalysisNotFoundError,
    AnalysisStore,
)
from app.services.change_impact import ChangeImpactService
from app.services.datahub_writeback import (
    DataHubApplyError,
    DataHubPreviewTimeoutError,
    DataHubWritebackService,
    MutationsDisabledError,
    SdkDataHubMutationGateway,
    merge_managed_section,
    render_managed_section,
)


SOURCE_URN = (
    "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.orders,PROD)"
)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, *, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class FakeGateway:
    def __init__(self, description: str = "Existing documentation.") -> None:
        self.description = description
        self.read_calls = 0
        self.patch_calls: list[tuple[str, str]] = []
        self.read_delay = 0.0
        self.fail_after_patch = False

    def get_description(self, urn: str) -> str:
        self.read_calls += 1
        if self.read_delay:
            time.sleep(self.read_delay)
        return self.description

    def patch_description(self, urn: str, description: str) -> None:
        self.patch_calls.append((urn, description))
        self.description = description
        if self.fail_after_patch:
            raise RuntimeError("simulated transport failure after send")


class LiveNamedMockProvider(ContextProvider):
    name = "datahub"

    async def healthcheck(self) -> tuple[bool, str]:
        return True, "Mock DataHub is ready."

    async def build_context(self, request: ChangeRequest) -> ContextGraph:
        root = Asset(
            urn=request.asset_urn,
            name="Orders",
            asset_type="dataset",
            platform="snowflake",
            criticality="high",
            fields=[request.column],
            dependency_type="Source asset",
            hops=0,
        )
        affected = Asset(
            urn="urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.order_metrics,PROD)",
            name="Order Metrics",
            asset_type="dataset",
            platform="dbt",
            criticality="high",
            owners=["Data Platform"],
            metadata_sources={"owners": "datahub"},
        )
        return ContextGraph(root_asset=root, assets=[root, affected], edges=[])


def change_request() -> ChangeRequest:
    return ChangeRequest(
        asset_urn=SOURCE_URN,
        column="order_id",
        change_type="rename",
        new_value="purchase_id",
        reason="Standardize the identifier",
    )


def analysis_result(analysis_id: str) -> AnalysisResult:
    root = Asset(
        urn=SOURCE_URN,
        name="Orders",
        asset_type="dataset",
        platform="snowflake",
        criticality="high",
        dependency_type="Source asset",
        hops=0,
    )
    affected = Asset(
        urn="urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.consumer,PROD)",
        name="Consumer",
        asset_type="dataset",
        platform="dbt",
        criticality="high",
    )
    return AnalysisResult(
        analysis_id=analysis_id,
        provider="datahub",
        decision="BLOCK",
        risk_score=77,
        raw_risk_score=77,
        risk_level="CRITICAL",
        factors=[
            RiskFactor(
                label="Breaking schema operation",
                points=25,
                evidence="Renames require coordinated downstream migration.",
            )
        ],
        affected_assets=[affected],
        required_approvals=["Data Platform"],
        explanation="A high-impact consumer requires coordinated review.",
        artifacts=GeneratedArtifacts(
            migration_sql="-- review only\nALTER TABLE orders ADD COLUMN purchase_id VARCHAR;",
            compatibility_sql="SELECT 1;",
            data_tests_yaml="version: 2",
            rollback_plan=["Stop dual writes.", "Remove the compatibility column."],
            pull_request_summary="Review the rename.",
        ),
        root_asset=root,
        lineage_edges=[],
    )


def stored_analysis(
    *, clock: MutableClock | None = None, analysis_id: str = "analysis-1"
):
    store = AnalysisStore(ttl_seconds=60, max_entries=5, clock=clock)
    entry = store.put(change_request(), analysis_result(analysis_id))
    return store, entry


def test_store_expiration_and_maximum_size_behavior():
    clock = MutableClock()
    store = AnalysisStore(ttl_seconds=60, max_entries=2, clock=clock)
    for analysis_id in ("analysis-1", "analysis-2", "analysis-3"):
        store.put(change_request(), analysis_result(analysis_id))

    assert len(store) == 2
    with pytest.raises(AnalysisNotFoundError):
        store.get("analysis-1")

    clock.advance(seconds=61)
    with pytest.raises(AnalysisExpiredError):
        store.get("analysis-3")
    assert len(store) == 0


@pytest.mark.asyncio
async def test_preview_is_read_only_and_preserves_existing_documentation():
    _, entry = stored_analysis()
    gateway = FakeGateway("Existing owner-authored documentation.\n")
    service = DataHubWritebackService(enabled=False, gateway=gateway)

    preview = await service.preview(entry)

    assert gateway.patch_calls == []
    assert preview.mutation.resulting_description.startswith(
        "Existing owner-authored documentation.\n"
    )
    assert preview.mutation.managed_section in preview.mutation.resulting_description
    assert preview.mutations_enabled is False
    assert preview.record.risk_score == 77
    assert preview.record.no_migration_executed is True


@pytest.mark.asyncio
async def test_apply_is_rejected_when_mutations_are_disabled():
    _, entry = stored_analysis()
    gateway = FakeGateway()
    service = DataHubWritebackService(enabled=False, gateway=gateway)

    with pytest.raises(MutationsDisabledError):
        await service.apply(entry)

    assert gateway.read_calls == 0
    assert gateway.patch_calls == []


@pytest.mark.asyncio
async def test_successful_writeback_is_idempotent():
    _, entry = stored_analysis()
    gateway = FakeGateway()
    service = DataHubWritebackService(enabled=True, gateway=gateway)

    first = await service.apply(entry)
    second = await service.apply(entry)

    assert first.status == "applied"
    assert first.idempotent is False
    assert second.status == "already_applied"
    assert second.idempotent is True
    assert len(gateway.patch_calls) == 1
    assert "No migration SQL was executed" in gateway.description
    assert entry.record.analysis_id in gateway.description


@pytest.mark.asyncio
async def test_preview_timeout_never_starts_a_mutation():
    _, entry = stored_analysis()
    gateway = FakeGateway()
    gateway.read_delay = 0.05
    service = DataHubWritebackService(
        enabled=True,
        gateway=gateway,
        timeout_seconds=0.005,
    )

    with pytest.raises(DataHubPreviewTimeoutError):
        await service.preview(entry)

    assert gateway.patch_calls == []


@pytest.mark.asyncio
async def test_partial_failure_reports_unknown_outcome_honestly():
    _, entry = stored_analysis()
    gateway = FakeGateway()
    gateway.fail_after_patch = True
    service = DataHubWritebackService(enabled=True, gateway=gateway)

    with pytest.raises(DataHubApplyError) as exc_info:
        await service.apply(entry)

    assert exc_info.value.mutation_state == "unknown"
    assert len(gateway.patch_calls) == 1
    assert entry.record.analysis_id in gateway.description


def test_managed_section_replacement_preserves_surrounding_documentation():
    _, entry = stored_analysis()
    section = render_managed_section(entry.record)
    existing = f"Before the record.\n\n{section}\n\nAfter the record."
    updated_record = entry.record.model_copy(update={"risk_score": 91})

    merged = merge_managed_section(
        existing,
        entry.record.analysis_id,
        render_managed_section(updated_record),
    )

    assert merged.startswith("Before the record.\n\n")
    assert merged.endswith("\n\nAfter the record.")
    assert "91/100" in merged
    assert merged.count("LINEAGESHIELD:BEGIN") == 1


def test_managed_section_escapes_user_controlled_html():
    _, entry = stored_analysis()
    unsafe_change = entry.record.proposed_change.model_copy(
        update={"reason": "<script>unsafe()</script> <!-- marker -->"}
    )
    unsafe_record = entry.record.model_copy(
        update={"proposed_change": unsafe_change}
    )

    section = render_managed_section(unsafe_record)

    assert "<script>" not in section
    assert "&lt;script&gt;unsafe()&lt;/script&gt;" in section
    assert section.count("LINEAGESHIELD:BEGIN") == 1


def test_sdk_gateway_builds_one_description_only_patch():
    class FakeEntities:
        def __init__(self) -> None:
            self.updates = []

        def get(self, urn: str):
            return type("Entity", (), {"description": "Existing"})()

        def update(self, patch) -> None:
            self.updates.append(patch)

    entities = FakeEntities()
    client = type("Client", (), {"entities": entities})()
    gateway = SdkDataHubMutationGateway(client=client)

    gateway.patch_description(SOURCE_URN, "Preserved plus managed section")

    assert len(entities.updates) == 1
    mcps = entities.updates[0].build()
    assert len(mcps) == 1
    assert mcps[0].aspectName == "editableDatasetProperties"
    payload = json.loads(mcps[0].aspect.value.decode())
    assert payload == [
        {
            "op": "add",
            "path": "/description",
            "value": "Preserved plus managed section",
        }
    ]


def install_api_test_services(monkeypatch, *, enabled: bool, gateway: FakeGateway):
    store = AnalysisStore(ttl_seconds=60, max_entries=10)
    monkeypatch.setattr(
        main_module,
        "service",
        ChangeImpactService(LiveNamedMockProvider()),
    )
    monkeypatch.setattr(main_module, "analysis_store", store)
    monkeypatch.setattr(
        main_module,
        "writeback_service",
        DataHubWritebackService(enabled=enabled, gateway=gateway),
    )
    return TestClient(main_module.app), store


def run_api_analysis(client: TestClient) -> dict:
    response = client.post("/api/analyze", json=change_request().model_dump())
    assert response.status_code == 200
    return response.json()


def test_successful_analysis_is_stored_and_never_mutates(monkeypatch):
    gateway = FakeGateway()
    client, store = install_api_test_services(
        monkeypatch,
        enabled=True,
        gateway=gateway,
    )

    result = run_api_analysis(client)

    stored = store.get(result["analysis_id"])
    assert stored.record.decision == result["decision"]
    assert gateway.read_calls == 0
    assert gateway.patch_calls == []


def test_apply_requires_confirmation_and_rejects_disabled_mode(monkeypatch):
    gateway = FakeGateway()
    client, _ = install_api_test_services(
        monkeypatch,
        enabled=False,
        gateway=gateway,
    )
    result = run_api_analysis(client)

    missing_confirmation = client.post(
        "/api/writeback/apply",
        json={"analysis_id": result["analysis_id"]},
    )
    disabled = client.post(
        "/api/writeback/apply",
        json={
            "analysis_id": result["analysis_id"],
            "confirmation": "RECORD_IN_DATAHUB",
        },
    )

    assert missing_confirmation.status_code == 422
    assert disabled.status_code == 403
    assert disabled.json()["detail"]["code"] == "mutations_disabled"
    assert gateway.patch_calls == []


def test_unknown_analysis_and_browser_supplied_values_are_rejected(monkeypatch):
    gateway = FakeGateway()
    client, _ = install_api_test_services(
        monkeypatch,
        enabled=True,
        gateway=gateway,
    )
    result = run_api_analysis(client)

    unknown = client.post(
        "/api/writeback/apply",
        json={
            "analysis_id": "not-stored",
            "confirmation": "RECORD_IN_DATAHUB",
        },
    )
    tampered = client.post(
        "/api/writeback/apply",
        json={
            "analysis_id": result["analysis_id"],
            "confirmation": "RECORD_IN_DATAHUB",
            "risk_score": 0,
            "decision": "ALLOW",
        },
    )

    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "analysis_not_found"
    assert tampered.status_code == 422
    assert gateway.patch_calls == []


def test_api_preview_then_apply_uses_stored_analysis(monkeypatch):
    gateway = FakeGateway()
    client, _ = install_api_test_services(
        monkeypatch,
        enabled=True,
        gateway=gateway,
    )
    result = run_api_analysis(client)

    preview = client.post(
        "/api/writeback/preview",
        json={"analysis_id": result["analysis_id"]},
    )
    applied = client.post(
        "/api/writeback/apply",
        json={
            "analysis_id": result["analysis_id"],
            "confirmation": "RECORD_IN_DATAHUB",
        },
    )
    repeated = client.post(
        "/api/writeback/apply",
        json={
            "analysis_id": result["analysis_id"],
            "confirmation": "RECORD_IN_DATAHUB",
        },
    )

    assert preview.status_code == 200
    assert preview.json()["record"]["decision"] == result["decision"]
    assert preview.json()["record"]["risk_score"] == result["risk_score"]
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"
    assert repeated.json()["status"] == "already_applied"
    assert len(gateway.patch_calls) == 1


def test_api_rejects_expired_analysis(monkeypatch):
    clock = MutableClock()
    gateway = FakeGateway()
    store = AnalysisStore(ttl_seconds=1, max_entries=10, clock=clock)
    monkeypatch.setattr(
        main_module,
        "service",
        ChangeImpactService(LiveNamedMockProvider()),
    )
    monkeypatch.setattr(main_module, "analysis_store", store)
    monkeypatch.setattr(
        main_module,
        "writeback_service",
        DataHubWritebackService(enabled=True, gateway=gateway),
    )
    client = TestClient(main_module.app)
    result = run_api_analysis(client)
    clock.advance(seconds=2)

    response = client.post(
        "/api/writeback/apply",
        json={
            "analysis_id": result["analysis_id"],
            "confirmation": "RECORD_IN_DATAHUB",
        },
    )

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "analysis_expired"
    assert gateway.patch_calls == []


def test_api_partial_failure_returns_unknown_mutation_state(monkeypatch):
    gateway = FakeGateway()
    gateway.fail_after_patch = True
    client, _ = install_api_test_services(
        monkeypatch,
        enabled=True,
        gateway=gateway,
    )
    result = run_api_analysis(client)

    response = client.post(
        "/api/writeback/apply",
        json={
            "analysis_id": result["analysis_id"],
            "confirmation": "RECORD_IN_DATAHUB",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"]["mutation_state"] == "unknown"
    assert response.json()["detail"]["retryable"] is True
