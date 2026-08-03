-- Temporary compatibility view; remove after consumers migrate.
CREATE OR REPLACE VIEW b2fd91.order_entry_db.analytics.order_details_compatible AS
SELECT
    *,
    PURCHASE_ID AS ORDER_ID
FROM b2fd91.order_entry_db.analytics.order_details;

