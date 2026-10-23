"""Stock à écouler et plan d'écoulement."""

from __future__ import annotations

from fastapi import APIRouter

from copilote.analyses import PlanEcoulement
from copilote.api.dependances import ApplicationDep

routeur = APIRouter(prefix="/stock", tags=["stock"])


@routeur.get("/plan-ecoulement", response_model=PlanEcoulement)
def plan_ecoulement(app: ApplicationDep) -> PlanEcoulement:
    return app.pilotage.plan_ecoulement()
