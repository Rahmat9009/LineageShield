from typing import Literal
from uuid import uuid4

from app.context.base import ContextProvider
from app.models import AnalysisResult, ChangeRequest, Decision
from app.services.artifact_generator import ArtifactGenerator
from app.services.risk_engine import RiskEngine


RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class ChangeImpactService:
    REVIEW_THRESHOLD = 25
    BLOCK_THRESHOLD = 50
    CRITICAL_THRESHOLD = 75

    def __init__(self, provider: ContextProvider) -> None:
        self.provider = provider
        self.risk_engine = RiskEngine()
        self.artifact_generator = ArtifactGenerator()

    @classmethod
    def classify_score(cls, score: int) -> tuple[Decision, RiskLevel]:
        if score >= cls.CRITICAL_THRESHOLD:
            return "BLOCK", "CRITICAL"
        if score >= cls.BLOCK_THRESHOLD:
            return "BLOCK", "HIGH"
        if score >= cls.REVIEW_THRESHOLD:
            return "REVIEW", "MEDIUM"
        return "ALLOW", "LOW"

    async def analyze(self, request: ChangeRequest) -> AnalysisResult:
        context = await self.provider.build_context(request)
        score, factors, affected = self.risk_engine.evaluate(request, context)
        raw_score = sum(factor.points for factor in factors)
        decision, risk_level = self.classify_score(score)

        approvals = sorted(
            {
                owner
                for asset in affected
                if asset.criticality in {"high", "critical"}
                for owner in asset.owners
            }
        )

        ranked = sorted(
            affected,
            key=lambda asset: (
                asset.criticality == "critical",
                asset.criticality == "high",
                asset.usage_score,
            ),
            reverse=True,
        )
        important_names = ", ".join(asset.name for asset in ranked[:3])
        leading_factors = ", ".join(
            factor.label.lower()
            for factor in sorted(
                factors,
                key=lambda factor: factor.points,
                reverse=True,
            )[:2]
        )
        threshold_reason = {
            "ALLOW": f"below the {self.REVIEW_THRESHOLD}-point review threshold",
            "REVIEW": (
                f"at or above the {self.REVIEW_THRESHOLD}-point review threshold"
            ),
            "BLOCK": f"at or above the {self.BLOCK_THRESHOLD}-point block threshold",
        }[decision]

        explanation = (
            f"This {request.change_type.replace('_', ' ')} reaches "
            f"{len(affected)} downstream asset(s)"
            f"{f', including {important_names}' if important_names else ''}. "
            f"The strongest deterministic evidence is {leading_factors or 'the operation base weight'}. "
            f"The score is {score}/100, {threshold_reason}, so the merge decision is {decision}."
        )

        return AnalysisResult(
            analysis_id=str(uuid4()),
            provider=self.provider.name,
            decision=decision,
            risk_score=score,
            raw_risk_score=raw_score,
            risk_level=risk_level,
            factors=factors,
            affected_assets=affected,
            required_approvals=approvals,
            explanation=explanation,
            artifacts=self.artifact_generator.generate(request),
            root_asset=context.root_asset,
            lineage_edges=context.edges,
            glossary_terms=context.glossary_terms,
            metadata_summary=context.metadata_summary,
            context_notes=context.context_notes,
        )
