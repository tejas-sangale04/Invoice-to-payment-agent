import logging
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException

from app.models.user import CurrentUser, Role
from app.services import firebase

logger = logging.getLogger(__name__)


def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    """Verify the Firebase ID token on every request. The role comes only from the token's
    custom claims, never from anything else the frontend sends."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    try:
        decoded = firebase.verify_id_token(token)
    except Exception as exc:
        logger.info("Rejected ID token: %s", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Invalid authentication token") from exc

    try:
        role = Role(decoded.get("role"))
    except ValueError:
        role = None  # signed in, but no role assigned yet
    return CurrentUser(uid=decoded["uid"], email=decoded.get("email"), role=role)


def require_role(minimum: Role) -> Callable[..., CurrentUser]:
    """Dependency factory: `Depends(require_role(Role.manager))` lets managers and admins in."""

    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(minimum):
            raise HTTPException(status_code=403, detail=f"Requires the {minimum} role")
        return user

    return dependency
