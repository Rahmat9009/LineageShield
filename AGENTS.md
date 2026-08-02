# LineageShield repository guide

## Purpose

LineageShield reviews a proposed schema change against live downstream DataHub lineage, calculates an explainable deterministic risk score, generates migration safeguards, and returns `ALLOW`, `REVIEW`, or `BLOCK`.

## Architecture

- `app/main.py`: FastAPI routes, static hosting, provider health, and structured API errors.
- `app/context/`: provider interface, live DataHub provider, and bundled demo fallback.
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
- Analysis is read-only. Do not enable mutations or change the user's DataHub/Docker installation.

## Never commit

- `.env`, access tokens, credentials, or secret-bearing logs
- virtual environments (`.venv/`, `.datahub-venv/`)
- editor caches, Python caches, or local test artifacts

## Guardrails

- Preserve existing endpoints and extend responses backward-compatibly.
- Never hardcode analysis results or replace live metadata with placeholder results.
- Do not fabricate owners, governance tags, usage, or quality signals.
- Keep risk scoring deterministic; generated safeguards cannot alter the score.
- Keep the live provider and `DataHubClient.from_env()` integration.
- Escape or use `textContent` for API/user strings; do not insert unsanitized HTML.
- Keep automated tests independent of live DataHub.

## Current limitations

- Live lineage is limited to two downstream hops and 60 displayed assets.
- The SDK response is normalized into source-to-dependent edges; intermediate live paths are shown only when returned as explicit edges.
- Live owner, tag, usage, quality, and glossary enrichment is not implemented.
- Safeguards are deterministic templates for review, not executed warehouse or GitHub changes.
- There is no DataHub write-back, authentication, or multi-user state.
