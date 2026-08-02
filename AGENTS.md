# LineageShield repository guide

## Purpose

LineageShield reviews a proposed schema change against live downstream DataHub lineage, calculates an explainable deterministic risk score, generates migration safeguards, and returns `ALLOW`, `REVIEW`, or `BLOCK`.

## Architecture

- `app/main.py`: FastAPI routes, static hosting, provider health, and structured API errors.
- `app/context/`: provider interface, live DataHub provider, pure metadata normalization helpers, and bundled demo fallback.
- `app/services/`: orchestration, deterministic risk scoring, and safeguard generation.
- `app/models.py`: validated API and context models.
- `app/static/`: vanilla HTML/CSS/JavaScript console. Keep it build-free unless a rewrite has a clear technical justification.
- `tests/`: isolated unit and API tests; they must not require live DataHub.

Keep DataHub calls in providers, scoring in services, and presentation in the frontend.

## Windows commands

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-datahub.txt
Copy-Item .env.live.example .env
python -m uvicorn app.main:app --reload
```

Run tests:

```powershell
python -m pytest -q
```

Import check:

```powershell
python -c "import app.main; print('import ok')"
```

## Live DataHub requirements

- DataHub must already be running and reachable at the configured GMS URL (local default: `http://localhost:8080`).
- Live mode uses `CONTEXT_PROVIDER=datahub` and `DataHubClient.from_env()`.
- Preserve column-level downstream lineage with entity-level lineage fallback.
- Preserve typed batch enrichment through the underlying `DataHubGraph.get_entities()` surface, with bounded single-entity SDK fallback.
- Keep metadata requests bounded (default concurrency 4, batch size 50, six-second request timeout, 20-second total enrichment timeout).
- Analysis is read-only. Do not enable mutations or change the user's DataHub/Docker installation.

## Never commit

- `.env`, access tokens, credentials, or secret-bearing logs
- virtual environments (`.venv/`, `.datahub-venv/`)
- editor caches, Python caches, or local test artifacts

## Guardrails

- Preserve existing endpoints and extend responses backward-compatibly.
- Never hardcode analysis results or replace live metadata with placeholder results.
- Do not fabricate owners, governance tags, usage, or quality signals.
- Preserve `metadata_sources`, criticality provenance/evidence, reference URNs, and `metadata_summary` when extending the API.
- Only treat exact DataHub structured/custom `criticality` values as explicit; keep the deterministic asset/platform/hop rule clearly labeled `inferred` otherwise.
- Keep `usage_score=0` and source `unavailable` until DataHub exposes a defensible normalized score; raw query counts must not be converted with an invented scale.
- Quality can use identifiable quality/assertion entries in `testResults`; unrelated governance, cost, and form tests must not set `quality_status`.
- Keep risk scoring deterministic; generated safeguards cannot alter the score.
- Keep the live provider and `DataHubClient.from_env()` integration.
- Escape or use `textContent` for API/user strings; do not insert unsanitized HTML.
- Keep automated tests independent of live DataHub.

## Current limitations

- Live lineage is limited to two downstream hops and 60 displayed assets.
- The SDK response is normalized into source-to-dependent edges; intermediate live paths are shown only when returned as explicit edges.
- Owners and ownership roles, tags, glossary terms, schema fields, names, descriptions, platforms, structured properties, and identifiable quality test results are retrieved when DataHub provides them. Missing aspects remain empty or `unknown` with explicit provenance.
- Usage is unavailable because the installed SDK/connected sample does not expose a trustworthy normalized score.
- DataHub Cloud assertions require the optional `acryl-datahub-cloud` extension, which is not part of this local project.
- The DataHub v2 entity SDK is experimental; the bulk path is on the underlying graph client and the public `EntityClient.get()` path is a bounded fallback.
- Synchronous SDK calls run in worker threads. Application timeouts stop awaiting them but cannot terminate an in-flight HTTP call.
- Safeguards are deterministic templates for review, not executed warehouse or GitHub changes.
- There is no DataHub write-back, authentication, or multi-user state.
