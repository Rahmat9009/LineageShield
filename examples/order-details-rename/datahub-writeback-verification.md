<!-- LINEAGESHIELD:BEGIN 1e9c9036-3d9e-40d9-a585-6bf2e686d2e4 -->
## LineageShield change-impact record

- **Analysis ID:** `1e9c9036-3d9e-40d9-a585-6bf2e686d2e4`
- **Analysis timestamp:** 2026-08-04T09:27:58.218069+00:00
- **Proposed change:** rename
- **Affected column:** `ORDER_ID`
- **New value:** `PURCHASE_ID`
- **Merge decision:** **BLOCK**
- **Risk:** 97/100 (CRITICAL)
- **Affected assets:** 24
- **Required approvals:** Andrea Garcia, Data Platform Team, Fiona Green, Ian Chen, Karen Okonkwo, Marco Santos, Priya Sharma, Sarah Chen
- **Review rationale:** This rename reaches 24 downstream asset(s), including Datahub Order Entries, Customer Analysis, Geographics. The strongest deterministic evidence is downstream dashboards and charts, large downstream blast radius. The score is 97/100, at or above the 50-point block threshold, so the merge decision is BLOCK.
- **Proposal rationale:** Standardize order identifiers across warehouse and BI assets

### Deterministic evidence
- +12 Rename operation: The operation has a base risk weight of 12.
- +20 Large downstream blast radius: 24 downstream assets are affected.
- +25 Downstream dashboards and charts: Datahub Order Entries, Customer Analysis, Geographics, Executive Summary, DAX Visual
- +20 Business-critical assets: Order Details (inferred fallback), Datahub Order Entries (inferred fallback), Order Details (inferred fallback), Customer Analytics Measures (inferred fallback), Essential KPI Measures (inferred fallback), Geographic Measures (inferred fallback), Product Perfromance Measures (inferred fallback), Order History (inferred fallback)
- +10 Existing quality failure: Order History
- +10 Cross-team coordination: 10 owner(s): Andrea Garcia, Backend Engineering Team, Data Platform Team, David Kim, Fiona Green, Ian Chen, Karen Okonkwo, Marco Santos, Priya Sharma, Sarah Chen

### Generated safeguard summary
- **Migration:** First generated migration step (not executed): ALTER TABLE b2fd91.order_entry_db.analytics.order_details
- **Rollback:** Pause deployments that consume PURCHASE_ID.; Rename PURCHASE_ID back to ORDER_ID.; Restore the previous compatibility view.; Re-run downstream data-quality checks.

_LineageShield recorded review metadata only. No migration SQL was executed._
<!-- LINEAGESHIELD:END 1e9c9036-3d9e-40d9-a585-6bf2e686d2e4 -->
