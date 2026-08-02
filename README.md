# LineageShield

**A metadata-aware change-impact agent that prevents schema changes from breaking data pipelines, dashboards, and ML systems.**

LineageShield accepts a proposed data change, investigates its downstream blast radius, assigns a transparent risk score, generates remediation artifacts, and returns an auditable merge decision.

This starter runs immediately in **demo mode** using a realistic metadata graph. A clean provider interface is included for connecting the DataHub Agent Context Kit or MCP Server.

## Working features

- Analyze rename, drop, type-change, and additive proposals
- Traverse a three-hop demo lineage graph
- Detect dashboards, pipelines, ML models, governed assets, owners, and quality failures
- Calculate a deterministic risk score
- Return `ALLOW`, `REVIEW`, or `BLOCK`
- Generate migration SQL, compatibility SQL, data tests, rollback steps, and a PR summary
- Export the result as JSON
- Run in a polished browser interface
- Run automated tests

## Run locally on Windows PowerShell

```powershell
cd lineageshield-starter

py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Run tests

```powershell
pytest
```

## Demo scenario

The default scenario proposes renaming:

```text
prod.customers.customer_region
```

to:

```text
sales_region
```

The demo graph contains a dbt model, an executive dashboard, an ML feature table, a production forecasting model, multiple owners, a PII tag, and a failed freshness assertion.

## Connect real DataHub

Copy the environment file:

```powershell
Copy-Item .env.example .env
```

Set:

```env
CONTEXT_PROVIDER=datahub
DATAHUB_GMS_URL=http://localhost:8080
DATAHUB_GMS_TOKEN=your-token
```

Install the optional packages:

```powershell
pip install -r requirements-datahub.txt
```

Then implement the marked integration in:

```text
app/context/datahub_provider.py
```

Recommended sequence:

1. Resolve the submitted asset with DataHub search.
2. Retrieve schema, ownership, tags, glossary terms, usage, and quality signals.
3. Traverse downstream lineage for one to three hops.
4. Normalize the result into the app's `ContextGraph`.
5. Add approved write-back for the risk decision and migration note.

## API

### Health

```http
GET /api/health
```

### Analyze

```http
POST /api/analyze
Content-Type: application/json
```

```json
{
  "asset_urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,prod.customers,PROD)",
  "column": "customer_region",
  "change_type": "rename",
  "new_value": "sales_region",
  "reason": "Standardize regional dimensions"
}
```

## Submission reminders

- Keep the repository public.
- Keep the Apache 2.0 license.
- Add screenshots and a simple architecture diagram.
- Include generated outputs under `examples/`.
- Clearly label demo mode and real DataHub mode.
- Deploy the app and record a demo under three minutes.
