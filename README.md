# LineageShield

**A live DataHub change-review agent that shows who and what a schema change can break before it is merged.**

LineageShield accepts a proposed column rename, type change, addition, or removal. It queries downstream lineage from DataHub, normalizes the affected datasets, pipelines, charts, dashboards, and ML assets, calculates a deterministic risk score, generates practical migration safeguards, and returns an auditable `ALLOW`, `REVIEW`, or `BLOCK` decision.

The project is built for the **DataHub Agent Hackathon** and is designed for a concise three-minute demonstration.

## The problem

A schema change that looks local in a pull request can silently break dbt models, scheduled pipelines, executive dashboards, and production features. Reviewers rarely have the complete dependency context at merge time. LineageShield brings that context into a single pre-merge investigation and explains every point in its decision.

## How DataHub is used

Live mode uses `DataHubClient.from_env()` to:

1. Request downstream column-level lineage for the submitted field.
2. Fall back to downstream entity-level lineage when fine-grained lineage is absent.
3. Traverse up to two hops, remove duplicate URNs, and normalize up to 60 affected assets.
4. Fetch typed entity aspects for the root and downstream datasets, dashboards, charts, data jobs, and supported ML entities in bounded batches.
5. Resolve referenced users, groups, ownership types, tags, and glossary terms to their DataHub display names while retaining the full URNs.
6. Return per-field provenance and a metadata coverage summary with the real provider evidence.

Direct metadata can include display name, platform, description, schema fields, owners, tags, glossary terms, structured properties, and identifiable quality test results. Every asset marks values as `datahub`, `lineage`, `inferred`, `fallback`, `unavailable`, or `demo`; inferred criticality is never represented as stored DataHub metadata.

Normal analysis remains read-only. An optional, disabled-by-default write-back flow can record a reviewed result on the root dataset only after a separate preview and explicit confirmation. LineageShield never creates pull requests or executes generated SQL.

## Architecture

```text
Browser (vanilla HTML/CSS/JS)
        │
        ▼
FastAPI routes
  ├── /api/analyze ──► ChangeImpactService
  │                       ├── ContextProvider
  │                       │     ├── DataHubContextProvider (live)
  │                       │     └── DemoContextProvider (offline fallback)
  │                       ├── RiskEngine (deterministic)
  │                       └── ArtifactGenerator (review templates)
  │                              │
  │                              └──► AnalysisStore (bounded snapshot)
  └── /api/writeback/* ──► AnalysisStore ──► DataHubWritebackService
                                                 └── description JSON Patch
```

The frontend has no build step or paid visualization dependency. Its SVG lineage view is generated only from API-returned assets and edges, with the affected-assets explorer as the accessible list alternative.

## Local setup on Windows

Prerequisites:

- Python 3.11
- A local DataHub quickstart already running at `http://localhost:8080`
- A DataHub token only if your local instance requires one

Create the environment and install the live provider:

```powershell
cd lineageshield-starter
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-datahub.txt
```

Create the local configuration:

```powershell
Copy-Item .env.live.example .env
```

The live configuration is:

```env
APP_NAME=LineageShield
CONTEXT_PROVIDER=datahub
DATAHUB_GMS_URL=http://localhost:8080
DATAHUB_GMS_TOKEN=
DATAHUB_MUTATIONS_ENABLED=false
DATAHUB_MUTATION_TIMEOUT_SECONDS=12
ANALYSIS_STORE_TTL_SECONDS=1800
ANALYSIS_STORE_MAX_ENTRIES=100
DATAHUB_HEALTH_TIMEOUT_SECONDS=6
DATAHUB_LINEAGE_TIMEOUT_SECONDS=30
DATAHUB_ENRICHMENT_TIMEOUT_SECONDS=20
DATAHUB_ENRICHMENT_REQUEST_TIMEOUT_SECONDS=6
DATAHUB_ENRICHMENT_CONCURRENCY=4
DATAHUB_ENRICHMENT_BATCH_SIZE=50
```

Do not commit `.env` or print a real token. Start LineageShield:

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## Sample hackathon scenario

Use **Sample scenario** in the proposal panel. It loads the live showcase asset:

```text
urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)
```

The proposal renames `ORDER_ID` to `PURCHASE_ID`. With the local showcase metadata loaded, DataHub returns the real downstream blast radius (approximately 24 assets in the current environment). The exact count can change with the metadata in DataHub; LineageShield never hardcodes it.

Demo flow for judges:

1. Confirm the header says **Live DataHub connected** and provider `datahub`.
2. Load the sample and run the investigation.
3. Read the merge decision and four summary metrics first.
4. Select nodes in the SVG graph and filter the dependency explorer.
5. Expand the deterministic risk evidence and show the score composition.
6. Review Migration, Compatibility, Tests, Rollback, and PR Summary.
7. Export the complete JSON report.
8. Open **Record in DataHub**, preview the exact patch, and show that Apply is disabled by default.

## Current capabilities

- Live DataHub connection and retryable failure state
- Column-level downstream lineage with entity-level fallback
- De-duplication and typed entity enrichment for the root and downstream assets
- Resolved DataHub display names for users, groups, ownership roles, tags, and glossary terms, with original URNs retained in the API
- Real dataset schema fields, descriptions, structured properties, and platform metadata when present
- Real owner values used for required approvals on high- and critical-impact assets
- Quality status only when DataHub test results contain an identifiable quality or assertion signal; otherwise `unknown`
- Per-field metadata provenance and aggregate enrichment coverage in every analysis response
- Explicit DataHub criticality from exact structured/custom properties when available; deterministic inferred criticality otherwise
- Interactive SVG blast-radius view using real API results
- Search and filters for asset type, platform, and criticality
- Keyboard-accessible node inspection, tabs, controls, and visible focus
- Deterministic risk factors with visible point contributions and evidence
- Explicit thresholds:
  - `0–24`: `ALLOW`
  - `25–49`: `REVIEW`
  - `50–74`: `BLOCK` / high risk
  - `75–100`: `BLOCK` / critical risk
- Generated migration SQL, compatibility SQL, schema tests, rollback steps, and PR summary
- Copy actions, individual artifact downloads, and full JSON export
- Structured provider health and analysis errors without browser alerts
- A two-step, root-only DataHub write-back with an exact preview, explicit confirmation, read-back receipt, and idempotent repeat behavior

## Safe DataHub write-back

Write-back uses one JSON Patch operation on the reviewed root dataset's `editableDatasetProperties.description` field. LineageShield first reads the effective description, preserves it byte-for-byte, and appends or replaces only the matching, clearly delimited block:

```text
<!-- LINEAGESHIELD:BEGIN <analysis-id> -->
...
<!-- LINEAGESHIELD:END <analysis-id> -->
```

The block records the analysis ID and UTC analysis timestamp, proposed change and affected column, optional new value, merge decision, deterministic risk score and level, affected asset count, real required-approval labels, concise evidence, migration and rollback summaries, and an explicit statement that no migration was executed. It does not change downstream assets, owners, tags, terms, quality signals, structured properties, or warehouse data.

The workflow is deliberately two-step:

1. `POST /api/writeback/preview` accepts only a completed `analysis_id`, reads the current description, and returns the exact managed section and complete resulting description. It never mutates DataHub and works while mutations are disabled.
2. `POST /api/writeback/apply` accepts the same `analysis_id` plus the exact confirmation value `RECORD_IN_DATAHUB`. It rejects disabled mode, missing confirmation, and unknown or expired analyses. All decision data comes from the server-side snapshot, never browser-supplied scores or decisions.

To enable Apply for a deliberate test, change only the local process configuration and restart:

```powershell
$env:DATAHUB_MUTATIONS_ENABLED = "true"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Stop that process and remove the temporary session variable to return to the safe default:

```powershell
Remove-Item Env:DATAHUB_MUTATIONS_ENABLED
```

Do not set the tracked example files to `true`, and do not commit `.env`. Repeating Apply for the same analysis re-reads DataHub and returns `already_applied` without sending another patch when the managed section already matches.

To remove a test record, open the root asset's Documentation editor in DataHub, delete the exact block from its `LINEAGESHIELD:BEGIN <analysis-id>` marker through its matching `END` marker, and save without changing the surrounding text. To replace it, remove that block and apply a newly completed investigation. If your DataHub version offers a **Revert edit** action and the asset originally used ingestion-owned documentation, use that action only when you intend to remove the entire editable description override.

## Enrichment performance and resilience

The installed DataHub v2 `EntityClient` exposes single-entity `get()` calls. To avoid a serial call per asset, LineageShield uses the SDK's typed OpenAPI `DataHubGraph.get_entities()` batch surface through the client, grouped by entity type and split into batches of 50. The public single-entity client remains a bounded fallback when the bulk surface is unavailable.

- At most four metadata requests run concurrently by default.
- Each metadata request has a six-second application deadline.
- The complete enrichment stage has a 20-second deadline.
- Immediate batch failures are split to isolate the bad record; a timed-out batch is not retried one entity at a time.
- Missing or failed metadata preserves the lineage result and safe URN fallback instead of failing the investigation.
- No URNs, access tokens, or response bodies are written to failure logs.

These values can be tuned with the `DATAHUB_ENRICHMENT_*` environment settings shown above. The lineage limit remains 60 downstream assets.

## Offline demo provider

For UI development when DataHub is intentionally unavailable, set:

```env
CONTEXT_PROVIDER=demo
```

This uses `app/data/demo_graph.json`. Demo metadata is a fallback only; the primary hackathon workflow is the live DataHub provider.

## API

Health and provider status:

```http
GET /api/health
```

Analyze a proposed change:

```http
POST /api/analyze
Content-Type: application/json
```

```json
{
  "asset_urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)",
  "column": "ORDER_ID",
  "change_type": "rename",
  "new_value": "PURCHASE_ID",
  "reason": "Standardize order identifiers across warehouse and BI assets"
}
```

Existing endpoints remain available, including `GET /api/demo-context`.

Preview a stored completed analysis without mutating:

```http
POST /api/writeback/preview
Content-Type: application/json

{"analysis_id": "<analysis-id>"}
```

Apply the server-stored record after explicit confirmation:

```http
POST /api/writeback/apply
Content-Type: application/json

{"analysis_id": "<analysis-id>", "confirmation": "RECORD_IN_DATAHUB"}
```

## Testing

Automated tests use mocked or bundled providers and do not require DataHub:

```powershell
python -m pytest -q
```

The suite covers risk thresholds, a large downstream blast radius, lineage fallback and duplicate removal, root and downstream enrichment, reference normalization and deduplication, partial failures and timeouts, metadata provenance, approval owners, readable URN fallbacks, analysis-store bounds and expiry, preview/apply safety, tamper rejection, description preservation, idempotency, and mocked FastAPI endpoints. It does not require a running DataHub server.

Import check:

```powershell
python -c "import app.main; print('LineageShield import OK')"
```

## Current limitations

- Live traversal is limited to two hops and 60 normalized downstream assets.
- DataHub lineage results are represented with the explicit edges available to the provider; the current live normalization connects returned dependents to the source when intermediate path edges are unavailable.
- Usage stays at `0` with provenance `unavailable`. The installed SDK exposes raw dataset usage timeseries rather than a canonical, defensible `0–100` popularity score, and the connected sample returned no usage records during capability inspection. LineageShield does not invent a normalization.
- DataHub Cloud's assertions client is not installed in the local open-source environment (`acryl-datahub-cloud` is required). Quality therefore uses only identifiable quality/assertion entries already present in DataHub's `testResults` aspect; all other assets remain `unknown`.
- DataHub has no universal criticality field in the retrieved aspects. Exact `criticality` structured/custom property values are treated as explicit; otherwise the existing deterministic asset-type/platform/hop inference is retained and labeled `inferred`.
- Reference names depend on the typed bulk OpenAPI endpoint. If a referenced user, group, ownership type, tag, or term cannot be resolved, the API keeps its full URN and supplies a readable URN fallback label.
- The installed DataHub v2 SDK reports its entity API as experimental. LineageShield isolates SDK failures and falls back safely, but future SDK upgrades should be regression-tested.
- Application timeouts stop waiting for synchronous SDK work; Python cannot forcibly terminate an already-running `to_thread` HTTP call, which may finish in the background.
- Completed-analysis storage is process-local, capped at 100 entries, and expires records after 30 minutes by default. It is lost on restart and is not suitable for multiple workers, durable audit, or production coordination.
- Preview and Apply each read the current effective description. Applying creates or updates DataHub's editable description layer; on assets whose visible description came only from ingestion, this can intentionally shadow later ingestion-owned description updates until the editable override is reverted.
- The installed `acryl-datahub` client is `1.6.0.6`; the verified local server is `v1.5.0.6` and advertises patch support. This SDK has no description-specific public patch builder, so the mutation adapter uses its generic `MetadataPatchProposal` scalar patch surface and is covered by a shape test. Regression-test this adapter on SDK upgrades.
- A timeout or transport error after patch submission has an honestly reported `unknown` mutation state. Inspect the root asset before retrying. The single-aspect design avoids multi-operation partial success but cannot prove whether an interrupted remote request committed.
- Generated safeguards are review templates. LineageShield does not execute SQL or write to GitHub.
- No authentication, billing, GitHub PR creation, downstream mutation, or multi-user durable state is included.

## Repository map

```text
app/
  context/       DataHub and demo context providers
  services/      Risk scoring, orchestration, artifact generation, analysis store, write-back
  static/        Enterprise review console and SVG lineage renderer
  data/          Bundled offline demo graph
tests/           Unit and FastAPI tests
```

LineageShield is licensed under Apache 2.0.
