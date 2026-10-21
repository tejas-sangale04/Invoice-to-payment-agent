from fastapi import APIRouter, Depends

from app.api.deps import Db
from app.models.rules import BusinessRules
from app.models.user import CurrentUser, Role
from app.services import rules as svc
from app.services.auth import require_role

router = APIRouter(tags=["business rules"])


@router.get("/business-rules", response_model=BusinessRules)
def get_rules(db: Db, _: CurrentUser = Depends(require_role(Role.admin))) -> BusinessRules:
    return svc.get_rules(db)


@router.put("/business-rules", response_model=BusinessRules)
def put_rules(
    body: BusinessRules, db: Db, _: CurrentUser = Depends(require_role(Role.admin))
) -> BusinessRules:
    return svc.save_rules(db, body)
