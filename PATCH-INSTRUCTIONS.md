# Live DataHub setup

The live DataHub lineage patch is already incorporated in this repository. Do not copy older provider, risk-engine, or frontend files over the current implementation.

Create a local `.env` from the live example:

```powershell
Copy-Item .env.live.example .env
```

Confirm these values and add a token only if the local instance requires one:

```env
APP_NAME=LineageShield
CONTEXT_PROVIDER=datahub
DATAHUB_GMS_URL=http://localhost:8080
DATAHUB_GMS_TOKEN=
DATAHUB_MUTATIONS_ENABLED=false
```

Keep Docker Desktop and the DataHub quickstart running. Install the live dependencies, then start LineageShield:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-datahub.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The header should report **Live DataHub connected**. If DataHub is unavailable, the application still imports and serves an explicit retryable connection state.

The **Sample scenario** action uses:

```text
urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)
```

LineageShield first requests downstream column lineage and falls back to entity lineage. Owner, tag, usage, and quality enrichment remain later milestones; the provider does not fabricate them.
