from dataclasses import dataclass

from app.models.employee import Employee
from app.models.enums import Role


@dataclass(frozen=True)
class UserContext:
    """Identity of the caller, loaded from the verified JWT. Never derived from the chat message."""

    user_id: int
    name: str
    role: Role
    department_id: int | None
    manager_id: int | None
    access_token: str

    @classmethod
    def from_employee(cls, employee: Employee, access_token: str) -> "UserContext":
        return cls(
            user_id=employee.id,
            name=employee.name,
            role=employee.role,
            department_id=employee.department_id,
            manager_id=employee.manager_id,
            access_token=access_token,
        )
