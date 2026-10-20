from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import auth

from app.models.user import CurrentUser, Role, SetRoleRequest, UserOut
from app.services import firebase
from app.services.auth import get_current_user, require_role

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser = Depends(get_current_user)) -> UserOut:
    return UserOut(uid=user.uid, email=user.email, role=user.role)


@router.put("/users/{uid}/role", response_model=UserOut)
def set_user_role(
    uid: str,
    body: SetRoleRequest,
    _: CurrentUser = Depends(require_role(Role.admin)),
) -> UserOut:
    """Admin only. The user must sign in again (or refresh their token) to pick up the new role."""
    try:
        record = firebase.get_user(uid)
    except auth.UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc
    firebase.set_role_claim(uid, body.role.value)
    return UserOut(uid=uid, email=record.email, role=body.role)
