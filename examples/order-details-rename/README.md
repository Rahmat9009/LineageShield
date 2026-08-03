# Order Details rename: captured live example

This directory is a real LineageShield API capture from 2026-08-03 at 10:09:24 UTC. It is not demo-provider output. The analysis ID is `12d3b0db-9393-4c8c-87ce-a25ac57dbabf`.

## Proposed change

LineageShield reviewed this request against the local DataHub OSS metadata graph:

- Root: `urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)`
- Column: `ORDER_ID`
- Change: rename
- New name: `PURCHASE_ID`
- Rationale: Standardize order identifiers across warehouse and BI assets

## Exact result

| Result | Captured value |
| --- | --- |
| Decision | `BLOCK` |
| Risk | 97/100, `CRITICAL` |
| Raw risk | 97 |
| Downstream assets | 24 |
| Metadata entities enriched | 25/25, including the root |
| Explicit criticality values | 0; all criticality used here is labeled `inferred` |
| Provider | `datahub` |

The decision is `BLOCK` because the deterministic factors total 97 points: rename operation +12, large downstream blast radius +20, downstream dashboards and charts +25, business-critical assets +20, an existing quality failure +10, and cross-team coordination +10. The block threshold is 50.

## Live DataHub evidence

The 24 affected assets span the real platforms returned by DataHub: dbt (1), Looker (2), Power BI (11), Snowflake (2), and Tableau (8). The asset types are 19 datasets, four charts, and one dashboard. Enrichment completed without an isolated failure: owners were present on 9 assets, tags on 3, schema fields on 20, and glossary terms on 20.

The root asset owners are DataHub SE Team, David Kim, and Julia Novak. Across affected assets, the deterministic owner factor found 10 unique owners. The eight required approvals are Andrea Garcia, Data Platform Team, Fiona Green, Ian Chen, Karen Okonkwo, Marco Santos, Priya Sharma, and Sarah Chen; LineageShield requires approvals only from owners attached to high- or critical-impact affected assets.

Quality evidence is kept distinct from structured-property scores. DataHub reported one passing quality test on the root and one failing quality test on the downstream Snowflake `Order History` asset. That failure contributes 10 risk points. Of the 24 downstream assets, 23 remain `unknown` rather than being assigned invented quality states.

## Agent Context Kit investigation

The read-only `datahub-agent-context` 1.6.0.17 trace completed in 572 ms with no tool failures:

1. `get_entities.root` retrieved the root context in 208 ms.
2. `get_lineage.column_downstream` returned 0 references in 70 ms.
3. `get_lineage.dataset_downstream` returned 24 references in 289 ms.

The trace therefore records a truthful column-lineage fallback: the submitted field had no usable fine-grained downstream evidence, so dataset-level downstream lineage was requested. Provider evidence and deterministic scoring remain authoritative; the agent narrative cannot alter the score, decision, approvals, artifacts, or mutation outcome. No LLM was used.

## Generated safeguards

- [migration.sql](migration.sql) — generated rename statement for review
- [compatibility.sql](compatibility.sql) — temporary compatibility view
- [schema-tests.yml](schema-tests.yml) — generated schema-test template
- [rollback.sql](rollback.sql) — the API did not return executable rollback SQL; this file preserves its four review-only rollback steps verbatim as SQL comments
- [pr-summary.md](pr-summary.md) — generated pull-request summary

The complete untouched result values are in [analysis.json](analysis.json), and the extracted sanitized tool trace is in [agent-trace.json](agent-trace.json). These safeguards are templates for human review. **No migration SQL was executed.**

## Write-back safety

[writeback-preview.json](writeback-preview.json) is the real preview for this analysis. It reports `mutations_enabled: false`, `already_applied: false`, and `preserves_existing_description: true`. Preview performed no mutation. Applying a stored result requires a separate call with the exact confirmation `RECORD_IN_DATAHUB` while mutations are deliberately enabled; this capture did not make that call. The stored analysis expired after its recorded 30-minute window, so judges should run a new analysis before testing preview or Apply.

