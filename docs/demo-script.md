# Judge demo script — 2:45

Before recording, start DataHub and one LineageShield process, confirm the Order Details sample exists, and open the app at 1440×900 or larger. If the final write-back will be demonstrated, deliberately enable mutations only for this process and plan to remove the matching managed block afterward.

## 0:00–0:15 — Problem

**Screen:** Start on the LineageShield header and connected-provider status.

**Narration:** “A warehouse column rename can look harmless in a pull request while breaking models, dashboards, and reports nobody remembered to check. LineageShield turns DataHub lineage into an auditable merge decision before that change runs.”

## 0:15–0:35 — Proposed change

**Screen:** Click **Sample scenario**. Point to the Snowflake Order Details URN, `ORDER_ID`, rename, and `PURCHASE_ID`; click **Run investigation**.

**Narration:** “I’m proposing a real rename on the Order Details dataset: `ORDER_ID` becomes `PURCHASE_ID`. The request goes to the local API, which is connected to DataHub OSS. Analysis is read-only.”

## 0:35–1:10 — Real lineage and metadata

**Screen:** Show `BLOCK`, 97/100, and 24 assets. Pan the lineage graph, then filter or select examples from Power BI, Tableau, Looker, dbt, and Snowflake. Open an asset detail with owners and provenance.

**Narration:** “DataHub returned 24 downstream assets across five real platforms: 19 datasets, four charts, and one dashboard. LineageShield enriched all 25 entities including the root. Owners, schema, glossary terms, and quality come from DataHub when present. Criticality here is explicitly labeled inferred because the graph contains no exact criticality property.”

## 1:10–1:35 — Agent Context trace and deterministic risk

**Screen:** Expand **Agent investigation**, showing the three successful operations and fallback. Then expand the six risk factors.

**Narration:** “The Agent Context Kit resolved the root, found zero column-level references, and honestly fell back to 24 dataset-level references. The trace is sanitized and read-only. Deterministic factors—not a model narrative—sum to 97, including dashboard exposure, blast radius, one failing Order History quality test, and cross-team coordination.”

## 1:35–2:05 — Generated safeguards

**Screen:** Cycle through Migration, Compatibility, Tests, Rollback, and PR Summary. Pause on the compatibility view and rollback steps.

**Narration:** “The agent acts on the evidence by generating a migration statement, a temporary compatibility view, schema-test scaffolding, a four-step rollback plan, and a pull-request summary. These are review templates. Nothing is sent to a warehouse or GitHub, and no generated SQL was executed.”

## 2:05–2:30 — Confirmed DataHub write-back

**Screen:** Open **Record in DataHub**, inspect the exact preview and preservation warning, type `RECORD_IN_DATAHUB`, and click Apply. Open the root asset in DataHub and show only the matching LineageShield block.

**Narration:** “Recording the review is a separate, explicit action. The server uses its stored analysis, re-reads the description, and patches only this root dataset’s editable documentation. Repeating the same record is idempotent. This records review metadata—it does not run the migration or modify downstream assets.”

## 2:30–2:45 — Conclusion

**Screen:** Return to the decision and graph.

**Narration:** “LineageShield gives reviewers real lineage, truthful metadata provenance, deterministic policy, actionable safeguards, and a controlled audit record—all without a paid LLM and read-only by default.”

