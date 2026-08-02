# Enable live DataHub lineage

Copy these files into the corresponding locations in your existing
LineageShield project, replacing the old files:

- `app/context/datahub_provider.py`
- `app/services/risk_engine.py`
- `app/static/app.js`

Then create a file named `.env` in the project root with:

```env
APP_NAME=LineageShield
CONTEXT_PROVIDER=datahub
DATAHUB_GMS_URL=http://localhost:8080
DATAHUB_GMS_TOKEN=
DATAHUB_MUTATIONS_ENABLED=false
```

Keep Docker Desktop and the DataHub quickstart running.

Activate the LineageShield environment and restart the website:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

The status badge should say:

```text
Live DataHub connected
```

The default form now uses this real showcase asset:

```text
urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)
```

The first live version reads downstream lineage from DataHub. Owners, tags,
usage, quality assertions, write-back, and GitHub PR creation are later
milestones.
