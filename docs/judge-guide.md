# Judge guide

## Project in under 150 words

LineageShield is a DataHub-native schema-change review agent. Give it a dataset column rename, drop, type change, or addition; it queries live downstream lineage, enriches the affected assets with real DataHub metadata, executes a bounded read-only Agent Context Kit investigation, and applies an explainable deterministic risk policy. The result is `ALLOW`, `REVIEW`, or `BLOCK`, plus owner approvals and review-only migration, compatibility, test, rollback, and pull-request safeguards. Every metadata field carries provenance, missing evidence stays unknown, and inferred criticality is labeled inferred. No paid LLM is required. Analysis is read-only by default. Optional write-back is isolated behind preview, a server-side analysis snapshot, disabled-by-default mutations, and the exact confirmation `RECORD_IN_DATAHUB`; it can patch only the reviewed root dataset's editable description.

## Fastest-path demo

1. Open `http://127.0.0.1:8000` and confirm **Live DataHub connected**.
2. Select **Sample scenario**, then **Run investigation**.
3. Show the `BLOCK` decision, 97/100 risk, and 24 affected assets.
4. Inspect the graph, metadata filters, deterministic factors, and Agent Context trace.
5. Open each generated safeguard, export JSON, then open the read-only write-back preview.

Use the [two-minute-forty-five-second script](demo-script.md), [captured live result](../examples/order-details-rename/), and [manual screenshot checklist](screenshots/README.md).

## Offline demo provider

The offline provider is for UI evaluation when DataHub is intentionally unavailable:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`.env.example` selects `CONTEXT_PROVIDER=demo`. The bundled graph is clearly labeled demo evidence and is not the live hackathon result. Alternatively, `docker compose up --build` starts this same demo-provider configuration on port 8000.

## Full live DataHub setup

Prerequisites are Python 3.11 and an existing DataHub OSS instance whose GMS responds at `http://localhost:8080`. The Order Details sample must already exist in that metadata graph.

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-datahub.txt
Copy-Item .env.live.example .env
Invoke-WebRequest -UseBasicParsing http://localhost:8080/health
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

If GMS requires a token, put it only in the untracked `.env` as `DATAHUB_GMS_TOKEN`. Keep `DATAHUB_MUTATIONS_ENABLED=false`. Verify `http://127.0.0.1:8000/api/health` returns provider `datahub`, `connected: true`, and `mutations_enabled: false` before running the sample.

## Captured sample result

The repository snapshot at analysis ID `12d3b0db-9393-4c8c-87ce-a25ac57dbabf` returned:

- `BLOCK`, 97/100, `CRITICAL`; raw score 97
- 24 affected assets: dbt 1, Looker 2, Power BI 11, Snowflake 2, Tableau 8
- 25/25 entities enriched; owners on 9, tags on 3, schema fields on 20, glossary terms on 20; 0 enrichment failures
- 8 required approvals: Andrea Garcia, Data Platform Team, Fiona Green, Ian Chen, Karen Okonkwo, Marco Santos, Priya Sharma, Sarah Chen
- one passing root quality test and one failing downstream quality test on Snowflake `Order History`
- Agent Context column lineage 0, dataset fallback 24; all three read operations succeeded
- no explicit criticality metadata and no normalized usage score; those values were not invented

These are exact captured values, not hardcoded expectations. Live counts, ownership, quality, timings, and therefore the score can change when the DataHub metadata graph changes. Treat [analysis.json](../examples/order-details-rename/analysis.json) as the fixed reference and the current API as the live truth.

## Safe write-back test

Preview needs no mutation permission and performs zero patches:

```powershell
$analysis = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/analyze -ContentType application/json -Body '{"asset_urn":"urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)","column":"ORDER_ID","change_type":"rename","new_value":"PURCHASE_ID","reason":"Judge review"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/writeback/preview -ContentType application/json -Body (@{analysis_id=$analysis.analysis_id} | ConvertTo-Json)
```

For a deliberate local Apply test, stop the app, set `$env:DATAHUB_MUTATIONS_ENABLED="true"`, start exactly one app process, and run a fresh analysis and preview. Then submit only the stored ID and exact confirmation:

```powershell
$confirmation = @{analysis_id=$analysis.analysis_id; confirmation="RECORD_IN_DATAHUB"} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/writeback/apply -ContentType application/json -Body $confirmation
```

Inspect the root asset's Documentation in DataHub and repeat Apply once to verify `already_applied`. Stop the app and run `Remove-Item Env:DATAHUB_MUTATIONS_ENABLED`. To clean up, delete only the matching `LINEAGESHIELD:BEGIN <analysis-id>` through `END` block in DataHub's Documentation editor. Generated SQL is never executed by this workflow.

## Troubleshooting

- **Python:** use CPython 3.11. A copied virtual environment whose base interpreter moved must be deleted and recreated locally; never commit it.
- **Docker:** `docker compose up --build` runs only the bundled demo provider. Ensure Docker Desktop is running. If port 8000 is occupied, stop the other app or change the published port.
- **DataHub connectivity:** check `http://localhost:8080/health`, the GMS URL, token, and `CONTEXT_PROVIDER=datahub`. The repository does not start or seed DataHub.
- **Ports:** LineageShield uses 8000 and local GMS normally uses 8080. Use `Get-NetTCPConnection -State Listen -LocalPort 8000,8080` to identify conflicts.
- **Missing sample:** confirm the exact root URN exists in DataHub and has downstream lineage. Never substitute demo results as live evidence.
- **Expired analysis ID:** snapshots live for 30 minutes by default and disappear on restart. Run `/api/analyze` again, then preview or Apply the new ID.
- **Agent trace degraded:** provider evidence remains authoritative; inspect the sanitized failure type, confirm `datahub-agent-context==1.6.0.17`, and retry only after connectivity is healthy.

## Tests

```powershell
python -m pytest -q
python -m pytest tests/test_agent_context.py -q
python "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" skills\schema-change-impact-review
python -m compileall -q app tests
Get-Content -Raw app/static/api.js | node --input-type=module --check
Get-Content -Raw app/static/lineage.js | node --input-type=module --check
Get-Content -Raw app/static/app.js | node --input-type=module --check
```

The 51-test automated suite uses mocks and bundled providers; it requires no live DataHub server.
