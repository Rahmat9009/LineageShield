from uuid import uuid4

from app.context.base import ContextProvider
from app.models import AnalysisResult, ChangeRequest
from app.services.artifact_generator import ArtifactGenerator
from app.services.risk_engine import RiskEngine


class ChangeImpactService:
    def __init__(self, provider: ContextProvider) -> None:
        self.provider = provider
        self.risk_engine = RiskEngine()
        self.artifact_generator = ArtifactGenerator()

    async def analyze(self, request: ChangeRequest) -> AnalysisResult:
        context = await self.provider.build_context(request)
        score, factors, affected = self.risk_engine.evaluate(request, context)

        if score >= 75:
            decision, risk_level = "BLOCK", "CRITICAL"
        elif score >= 50:
            decision, risk_level = "BLOCK", "HIGH"
        elif score >= 25:
            decision, risk_level = "REVIEW", "MEDIUM"
        else:
            decision, risk_level = "ALLOW", "LOW"

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
        names = ", ".join(asset.name for asset in ranked[:4])

        explanation = (
            f"The proposed {request.change_type.replace('_', ' ')} affects "
            f"{len(affected)} downstream asset(s). "
            f"The most important dependencies are {names or 'none'}. "
            f"The deterministic score is {score}/100, so the decision is {decision}."
        )

        return AnalysisResult(
            analysis_id=str(uuid4()),
            provider=self.provider.name,
            decision=decision,
            risk_score=score,
            risk_level=risk_level,
            factors=factors,
            affected_assets=affected,
            required_approvals=approvals,
            explanation=explanation,
            artifacts=self.artifact_generator.generate(request),
        )
