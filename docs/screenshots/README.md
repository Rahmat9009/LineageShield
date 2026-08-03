# Manual screenshot checklist

## 1. `01-change-proposal.png`

Show the full proposal card with the exact Snowflake root URN, `ORDER_ID`, rename operation, `PURCHASE_ID`, and rationale. Include the header's **Live DataHub connected** status. Frame the form and status together; the Run button should be visible.

## 2. `02-block-decision-lineage.png`

Show `BLOCK`, 97/100 `CRITICAL`, 24 affected assets, and the widest useful portion of the lineage graph in one frame. Include the graph legend or platform labels. Use a 1440-pixel-wide viewport and collapse browser side panels so nodes remain readable.

## 3. `03-affected-assets-metadata.png`

Show the affected-assets explorer with a selected real asset and its platform, owner labels, criticality provenance, quality evidence, and metadata-source labels visible. Prefer the Snowflake `Order History` failing-quality asset; do not crop away the `inferred` or `datahub` provenance labels. A slightly taller viewport is useful.

## 4. `04-agent-context-trace.png`

Show trace status `completed`, `datahub-agent-context` 1.6.0.17, `llm_used: false` if rendered, all three successful operations, the 0-reference column result, the 24-reference dataset result, and the fallback reason. Frame the trace panel tightly enough for operation names and counts to be legible.

## 5. `05-generated-safeguards.png`

Show the safeguards panel with its tabs and one substantive artifact, preferably `compatibility.sql`. The filename, generated content, and review-only warning must be visible. Do not imply the SQL ran. If space allows, include the download controls.

## 6. `06-writeback-preview.png`

Show the root-only `editableDatasetProperties.description` preview, the analysis ID, `BLOCK`, 97/100, 24 assets, preservation statement, and “No migration SQL was executed.” With the safe default, include the visible warning that mutations are disabled. If this image will pair with the confirmed record in screenshot 07, start one deliberately mutation-enabled process, run a fresh analysis, and capture its preview before typing the confirmation. Do not click Apply until this capture is complete.

## 7. `07-datahub-record.png`

After a deliberate, explicitly confirmed Apply, open the reviewed root dataset in DataHub's Documentation view. Show the LineageShield record with the same analysis ID, decision, score, affected count, approvals, deterministic evidence, safeguards summary, and no-execution statement. Frame the dataset identity and managed block together. Capture only the matching record; remove it afterward by deleting its exact `LINEAGESHIELD:BEGIN <analysis-id>` through `END` block if the write-back was only for judging.
