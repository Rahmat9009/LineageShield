# LineageShield repository guide

## Purpose

LineageShield reviews a proposed schema change against live downstream DataHub lineage, runs a read-only Agent Context Kit investigation, calculates an explainable deterministic risk score, generates migration safeguards, and returns `ALLOW`, `REVIEW`, or `BLOCK`.

## Architecture

- `app/main.py`: FastAPI routes, static hosting, provider health, and structured API errors.
- `app/context/`: provider interface, live DataHub provider, pure metadata normalization helpers, and bundled demo fallback.
- `app/services/`: orchestration, deterministic risk scoring, safeguard generation, bounded analysis snapshots, the read-only Agent Context Kit adapter, and the isolated DataHub mutation service.
- `app/models.py`: validated API and context models.
- `app/static/`: vanilla HTML/CSS/JavaScript console. Keep it build-free unless a rewrite has a clear technical justification.
- `tests/`: isolated unit and API tests; they must not require live DataHub.

Keep DataHub reads in providers, scoring in services, the explicit mutation path in `datahub_writeback.py`, and presentation in the frontend.

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

Run the Agent Context and skill checks only:

```powershell
python -m pytest tests/test_agent_context.py -q
python "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" skills\schema-change-impact-review
```

Import check:

```powershell
python -c "import app.main; print('import ok')"
```

## Live DataHub requirements

- DataHub must already be running and reachable at the configured GMS URL (local default: `http://localhost:8080`).
- Live mode uses `CONTEXT_PROVIDER=datahub` and `DataHubClient.from_env()`.
- Normal live analysis runs `AgentContextService` with `datahub-agent-context==1.6.0.17`: `DataHubContext`, `get_entities()`, and `get_lineage()`.
- Agent Context calls are read-only and bounded (10 seconds per tool, 24 seconds total, 60 lineage results by default). Provider evidence remains authoritative if the kit fails.
- Preserve column-level downstream lineage with entity-level lineage fallback.
- Preserve typed batch enrichment through the underlying `DataHubGraph.get_entities()` surface, with bounded single-entity SDK fallback.
- Keep metadata requests bounded (default concurrency 4, batch size 50, six-second request timeout, 20-second total enrichment timeout).
- Analysis and preview are always read-only. Keep `DATAHUB_MUTATIONS_ENABLED=false` by default and never mutate outside the explicit confirmed Apply route.
- Write-back is restricted to a scalar patch of the reviewed root dataset's `editableDatasetProperties.description`; preserve surrounding documentation and do not mutate downstream assets.

## Never commit

- `.env`, access tokens, credentials, or secret-bearing logs
- virtual environments (`.venv/`, `.datahub-venv/`)
- editor caches, Python caches, or local test artifacts

## Write-back workflow

- Preview with `POST /api/writeback/preview` and `{"analysis_id": "..."}`. Preview reads the current root documentation and must perform zero mutations.
- Apply with `POST /api/writeback/apply` and `{"analysis_id": "...", "confirmation": "RECORD_IN_DATAHUB"}`. The route must use only the stored snapshot.
- Keep `DATAHUB_MUTATIONS_ENABLED=false` in tracked examples. For a deliberate local test, set `$env:DATAHUB_MUTATIONS_ENABLED="true"`, start one app process, perform the confirmed write, stop it, then run `Remove-Item Env:DATAHUB_MUTATIONS_ENABLED`.
- The written block contains the analysis ID/timestamp, proposed change, decision, score/level, affected count, approvals, deterministic evidence, migration/rollback summaries, and the no-execution statement.
- Remove a test record in DataHub's Documentation editor by deleting only its matching `LINEAGESHIELD:BEGIN <analysis-id>` through `END` block. Use DataHub's editable-description revert control only when the entire override should be removed.
- Apply re-reads and verifies the description. A timeout after submission is an `unknown` outcome; inspect DataHub before retrying.

## Agent Context workflow

- `app/services/agent_context.py` exposes only `get_entities` and `get_lineage` through the official `DataHubContext` manager. Never add a mutation call to this service.
- The live sequence is root entity context, column-level downstream lineage, then an honestly recorded dataset-level fallback when fine-grained results are empty or fail.
- Retain only sanitized operation status, durations, counts, and evidence URNs. Do not retain raw tool payloads, prompts, descriptions, tokens, or secret-bearing errors in `agent_trace`.
- Keep DataHub evidence, deterministic LineageShield calculations, and agent narrative visibly distinct. `llm_used` remains `false`; no paid-model key is required.
- Agent narrative cannot change scores, decisions, approvals, artifacts, write-back confirmation, or mutation outcomes.
- The reusable skill is in `skills/schema-change-impact-review/`. Keep its risk and safety references aligned with production behavior. It is contribution-ready but has not been submitted upstream.

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
- Never trust write-back record fields from the browser. Resolve the `analysis_id` through the bounded server-side store and require `RECORD_IN_DATAHUB` confirmation.
- Keep managed documentation delimited by analysis-specific `LINEAGESHIELD:BEGIN` and `LINEAGESHIELD:END` comments. Repeating the same record must remain idempotent.
- Keep Agent Context operations read-only during analysis. Mutation remains a separate preview/apply route even if the upstream package exports mutation tools.

## Current limitations

- Live lineage is limited to two downstream hops and 60 displayed assets.
- The SDK response is normalized into source-to-dependent edges; intermediate live paths are shown only when returned as explicit edges.
- Owners and ownership roles, tags, glossary terms, schema fields, names, descriptions, platforms, structured properties, and identifiable quality test results are retrieved when DataHub provides them. Missing aspects remain empty or `unknown` with explicit provenance.
- Usage is unavailable because the installed SDK/connected sample does not expose a trustworthy normalized score.
- DataHub Cloud assertions require the optional `acryl-datahub-cloud` extension, which is not part of this local project.
- The DataHub v2 entity SDK is experimental; the bulk path is on the underlying graph client and the public `EntityClient.get()` path is a bounded fallback.
- Synchronous SDK calls run in worker threads. Application timeouts stop awaiting them but cannot terminate an in-flight HTTP call.
- The Agent Context Kit package namespace eagerly imports mutation modules and can emit an experimental SDK warning, although LineageShield exposes and calls only read tools. Regression-test this boundary on upgrades.
- Agent Context column lineage can be empty on the local OSS sample while dataset lineage returns the complete 24-asset graph; keep that fallback visible in the trace.
- The agent narrative is a deterministic evidence summary. No optional LLM integration is currently enabled.
- Safeguards are deterministic templates for review, not executed warehouse or GitHub changes.
- The write-back snapshot store is in-memory only (default 30-minute TTL, 100 entries), is lost on restart, and is not safe for multi-worker production deployment.
- Write-back patches only the editable dataset description. It can shadow later ingestion-owned documentation until that editable override is removed or reverted in DataHub.
- The installed SDK lacks a description-specific public patch builder. `SdkDataHubMutationGateway` uses the generic `MetadataPatchProposal` scalar patch supported by the verified patch-capable local server; keep its patch-shape regression test.
- There is no authentication, GitHub PR creation, billing, downstream mutation, or durable multi-user state.
