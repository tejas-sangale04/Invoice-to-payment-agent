from fastapi import APIRouter, Depends

from app.api.deps import Db
from app.models.dashboard import DashboardMetrics
from app.models.user import CurrentUser, Role
from app.services import dashboard as svc
from app.services.auth import require_role

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/metrics", response_model=DashboardMetrics)
def dashboard_metrics(
    db: Db, _: CurrentUser = Depends(require_role(Role.manager))
) -> DashboardMetrics:
    return svc.metrics(db)
