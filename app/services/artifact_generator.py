from app.models import ChangeRequest, GeneratedArtifacts


class ArtifactGenerator:
    def generate(self, request: ChangeRequest) -> GeneratedArtifacts:
        table_name = self._table_name(request.asset_urn)
        column = request.column
        new_value = request.new_value or ""

        if request.change_type == "rename":
            migration_sql = (
                f"ALTER TABLE {table_name}\n"
                f"RENAME COLUMN {column} TO {new_value};"
            )
            compatibility_sql = (
                "-- Temporary compatibility view; remove after consumers migrate.\n"
                f"CREATE OR REPLACE VIEW {table_name}_compatible AS\n"
                "SELECT\n"
                "    *,\n"
                f"    {new_value} AS {column}\n"
                f"FROM {table_name};"
            )
            rollback = [
                f"Pause deployments that consume {new_value}.",
                f"Rename {new_value} back to {column}.",
                "Restore the previous compatibility view.",
                "Re-run downstream data-quality checks.",
            ]
        elif request.change_type == "drop":
            migration_sql = (
                "-- Destructive operation: execute only after approvals.\n"
                f"ALTER TABLE {table_name}\nDROP COLUMN {column};"
            )
            compatibility_sql = (
                f"-- Deprecate {column}, migrate every consumer, then remove it."
            )
            rollback = [
                f"Restore {column} from the latest valid backup.",
                "Recreate affected compatibility views.",
                "Re-run downstream models and dashboards.",
            ]
        elif request.change_type == "type_change":
            migration_sql = (
                f"ALTER TABLE {table_name}\n"
                f"ALTER COLUMN {column} SET DATA TYPE {new_value};"
            )
            compatibility_sql = (
                f"CREATE OR REPLACE VIEW {table_name}_compatible AS\n"
                "SELECT\n"
                "    *,\n"
                f"    CAST({column} AS VARCHAR) AS {column}_legacy\n"
                f"FROM {table_name};"
            )
            rollback = [
                f"Cast {column} back to its previous type.",
                "Restore rejected or truncated values from backup.",
                "Re-run schema and nullability tests.",
            ]
        else:
            migration_sql = (
                f"ALTER TABLE {table_name}\n"
                f"ADD COLUMN {column} {new_value or 'VARCHAR'};"
            )
            compatibility_sql = "-- No compatibility view required."
            rollback = [f"Drop the newly added column {column}."]

        test_column = new_value if request.change_type == "rename" else column
        tests_yaml = (
            "version: 2\n"
            "models:\n"
            f"  - name: {table_name.split('.')[-1]}\n"
            "    columns:\n"
            f"      - name: {test_column}\n"
            "        tests:\n"
            "          - not_null\n"
            "          - accepted_values:\n"
            "              config:\n"
            "                severity: warn\n"
        )

        pr_summary = (
            "## LineageShield change review\n\n"
            f"**Asset:** `{request.asset_urn}`\n"
            f"**Change:** `{request.change_type}` on `{column}`\n"
            f"**New value:** `{request.new_value or 'N/A'}`\n\n"
            "### Generated safeguards\n"
            "- Migration SQL\n"
            "- Temporary compatibility layer\n"
            "- Data-quality tests\n"
            "- Rollback plan\n\n"
            "Review the complete impact report and obtain all required approvals."
        )

        return GeneratedArtifacts(
            migration_sql=migration_sql,
            compatibility_sql=compatibility_sql,
            data_tests_yaml=tests_yaml,
            rollback_plan=rollback,
            pull_request_summary=pr_summary,
        )

    @staticmethod
    def _table_name(urn: str) -> str:
        try:
            inner = urn.split(",", 1)[1]
            return inner.rsplit(",", 1)[0]
        except (IndexError, ValueError):
            return "prod.customers"
