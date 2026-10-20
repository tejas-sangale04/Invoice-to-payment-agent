from enum import StrEnum

from pydantic import BaseModel


class Role(StrEnum):
    staff = "staff"
    manager = "manager"
    admin = "admin"


# Each role includes everything the roles before it can do (Setup guide, Section 4).
ROLE_RANK: dict[Role, int] = {Role.staff: 1, Role.manager: 2, Role.admin: 3}


class CurrentUser(BaseModel):
    uid: str
    email: str | None = None
    role: Role | None = None

    def has_role(self, minimum: Role) -> bool:
        return self.role is not None and ROLE_RANK[self.role] >= ROLE_RANK[minimum]


class SetRoleRequest(BaseModel):
    role: Role


class UserOut(BaseModel):
    uid: str
    email: str | None = None
    role: Role | None = None
