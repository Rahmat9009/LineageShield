from app.models import Asset, ChangeRequest, ContextGraph, RiskFactor


class RiskEngine:
    """Calculate an explainable risk score from metadata evidence."""

    def evaluate(
        self,
        request: ChangeRequest,
        context: ContextGraph,
    ) -> tuple[int, list[RiskFactor], list[Asset]]:
        factors: list[RiskFactor] = []
        affected_by_urn = {
            asset.urn: asset
            for asset in context.assets
            if asset.urn != context.root_asset.urn
        }
        affected = list(affected_by_urn.values())

        def add(label: str, points: int, evidence: str) -> None:
            factors.append(
                RiskFactor(
                    label=label,
                    points=points,
                    evidence=evidence,
                )
            )

        base_points = {
            "add": 2,
            "rename": 12,
            "type_change": 18,
            "drop": 25,
        }[request.change_type]

        add(
            f"{request.change_type.replace('_', ' ').title()} operation",
            base_points,
            f"The operation has a base risk weight of {base_points}.",
        )

        affected_count = len(affected)
        if affected_count >= 10:
            add(
                "Large downstream blast radius",
                20,
                f"{affected_count} downstream assets are affected.",
            )
        elif affected_count >= 5:
            add(
                "Significant downstream blast radius",
                12,
                f"{affected_count} downstream assets are affected.",
            )
        elif affected_count >= 2:
            add(
                "Multiple downstream dependencies",
                6,
                f"{affected_count} downstream assets are affected.",
            )

        dashboards = [
            asset
            for asset in affected
            if asset.asset_type in {"dashboard", "chart"}
        ]
        if dashboards:
            dashboard_points = min(
                25,
                15 + (5 * (len(dashboards) - 1)),
            )
            add(
                "Downstream dashboards and charts",
                dashboard_points,
                ", ".join(asset.name for asset in dashboards[:8]),
            )

        ml_assets = [
            asset
            for asset in affected
            if asset.asset_type in {"ml_model", "feature_table"}
        ]
        if ml_assets:
            add(
                "Production ML dependency",
                25,
                ", ".join(asset.name for asset in ml_assets[:8]),
            )

        critical_assets = [
            asset
            for asset in affected
            if asset.criticality in {"high", "critical"}
        ]
        if critical_assets:
            critical_points = min(
                20,
                8 + (4 * len(critical_assets)),
            )
            add(
                "Business-critical assets",
                critical_points,
                ", ".join(
                    f"{asset.name} "
                    f"({'DataHub metadata' if asset.criticality_source == 'datahub' else 'inferred fallback'})"
                    for asset in critical_assets[:8]
                ),
            )

        governed_tags = {
            "PII",
            "SENSITIVE",
            "SOX",
            "HIPAA",
            "GDPR",
        }
        matching_tags = sorted(
            tag
            for tag in context.root_asset.tags
            if tag.upper() in governed_tags
        )
        if matching_tags:
            add(
                "Governed field or dataset",
                10,
                f"Governance tags: {', '.join(matching_tags)}",
            )

        failed_assets = [
            asset
            for asset in context.assets
            if asset.quality_status == "failing"
        ]
        if failed_assets:
            add(
                "Existing quality failure",
                10,
                ", ".join(asset.name for asset in failed_assets[:8]),
            )

        high_usage_assets = [
            asset
            for asset in affected
            if asset.usage_score >= 70
        ]
        if high_usage_assets:
            add(
                "High-usage downstream assets",
                10,
                ", ".join(
                    f"{asset.name} ({asset.usage_score})"
                    for asset in high_usage_assets[:8]
                ),
            )

        owners = sorted(
            {
                owner
                for asset in affected
                for owner in asset.owners
            }
        )
        if owners:
            add(
                "Cross-team coordination",
                min(10, 2 * len(owners)),
                f"{len(owners)} owner(s): {', '.join(owners)}",
            )

        score = min(
            100,
            sum(factor.points for factor in factors),
        )
        return score, factors, affected
