## LineageShield change review

**Asset:** `urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)`
**Change:** `rename` on `ORDER_ID`
**New value:** `PURCHASE_ID`

**Rationale:** Standardize order identifiers across warehouse and BI assets

### Generated safeguards
- Migration SQL
- Temporary compatibility layer
- Data-quality tests
- Rollback plan

Review the complete impact report and obtain all required approvals.

