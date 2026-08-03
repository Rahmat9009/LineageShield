-- LineageShield returned a review-only rollback plan, not executable rollback SQL.
-- 1. Pause deployments that consume PURCHASE_ID.
-- 2. Rename PURCHASE_ID back to ORDER_ID.
-- 3. Restore the previous compatibility view.
-- 4. Re-run downstream data-quality checks.

