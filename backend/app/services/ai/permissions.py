"""AI feature permissions.

This layer is deliberately *at least as strict* as the HRMS backend: it refuses
early with a clear message, and every mutation still goes through the backend
API, which re-checks the role. Authorization never depends on the frontend.
"""

import enum
import re

from app.models.enums import Role


class Capability(str, enum.Enum):
    POLICY_QA = "POLICY_QA"
    SQL_QUERY = "SQL_QUERY"
    VIEW_RAW_SQL = "VIEW_RAW_SQL"
    VIEW_TEAM_DATA = "VIEW_TEAM_DATA"
    VIEW_ALL_DATA = "VIEW_ALL_DATA"
    VIEW_PAYROLL = "VIEW_PAYROLL"
    CHECK_OWN_LEAVE = "CHECK_OWN_LEAVE"
    CREATE_OWN_LEAVE = "CREATE_OWN_LEAVE"
    APPROVE_LEAVE = "APPROVE_LEAVE"
    VIEW_PENDING_LEAVES = "VIEW_PENDING_LEAVES"
    CREATE_TICKET = "CREATE_TICKET"
    VIEW_OWN_TICKETS = "VIEW_OWN_TICKETS"
    MANAGE_TICKETS = "MANAGE_TICKETS"
    CREATE_ANNOUNCEMENT = "CREATE_ANNOUNCEMENT"
    MANAGE_PROJECTS = "MANAGE_PROJECTS"
    VIEW_AUDIT_ALL = "VIEW_AUDIT_ALL"


_EMPLOYEE = {
    Capability.POLICY_QA,
    Capability.SQL_QUERY,
    Capability.CHECK_OWN_LEAVE,
    Capability.CREATE_OWN_LEAVE,
    Capability.CREATE_TICKET,
    Capability.VIEW_OWN_TICKETS,
}
_MANAGER = _EMPLOYEE | {
    Capability.VIEW_RAW_SQL,
    Capability.VIEW_TEAM_DATA,
    Capability.APPROVE_LEAVE,
    Capability.VIEW_PENDING_LEAVES,
    Capability.MANAGE_TICKETS,
    Capability.CREATE_ANNOUNCEMENT,
    Capability.MANAGE_PROJECTS,
}
_ADMIN = set(Capability)

ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.EMPLOYEE: frozenset(_EMPLOYEE),
    Role.MANAGER: frozenset(_MANAGER),
    Role.ADMIN: frozenset(_ADMIN),
}

# Refusals state the rule only; they never confirm that a record exists.
REFUSAL_MESSAGES: dict[Capability, str] = {
    Capability.APPROVE_LEAVE: "You do not have permission to approve or reject leave requests.",
    Capability.VIEW_PENDING_LEAVES: "You do not have permission to view other employees' leave requests.",
    Capability.MANAGE_TICKETS: "You do not have permission to assign or update tickets.",
    Capability.CREATE_ANNOUNCEMENT: "You do not have permission to create announcements.",
    Capability.MANAGE_PROJECTS: "You do not have permission to create projects or assign employees to projects.",
    Capability.VIEW_PAYROLL: "You do not have permission to view payroll or salary information through the AI assistant. "
    "You can view your own payslips on the Finance page.",
    Capability.VIEW_AUDIT_ALL: "You do not have permission to view other users' AI activity.",
}

NEVER_EXPOSED_MESSAGE = (
    "Passwords, bank account details, PAN details and dates of birth are never available through the AI assistant."
)


def has_capability(role: Role, capability: Capability) -> bool:
    return capability in ROLE_CAPABILITIES.get(role, frozenset())


def refusal_for(capability: Capability) -> str:
    return REFUSAL_MESSAGES.get(capability, "You do not have permission to perform this action.")


class SensitiveCategory(str, enum.Enum):
    NEVER_EXPOSED = "NEVER_EXPOSED"
    PAYROLL = "PAYROLL"


_NEVER_EXPOSED_PATTERN = re.compile(
    r"\b(password|passwd|hashed_password|bank|account\s*(number|no)|ifsc|pan\b|pan[_\s]*(number|card|name|dob)|"
    r"date[_\s]+of[_\s]+birth|dob\b|birth\s*date|birthday)",
    re.IGNORECASE,
)
_PAYROLL_PATTERN = re.compile(
    r"\b(salary|salaries|payroll|pay\s*slip|payslip|compensation|ctc|gross\s+pay|net\s+pay|current_salary)",
    re.IGNORECASE,
)


def detect_sensitive_request(message: str) -> SensitiveCategory | None:
    """Detect requests for data that is restricted regardless of how the question is phrased."""
    if _NEVER_EXPOSED_PATTERN.search(message):
        return SensitiveCategory.NEVER_EXPOSED
    if _PAYROLL_PATTERN.search(message):
        return SensitiveCategory.PAYROLL
    return None


_INJECTION_PATTERN = re.compile(
    r"(ignore|disregard|forget|override)\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|your|system)\s+"
    r"(instructions?|rules?|prompts?|guardrails?)|you\s+are\s+now\s+|reveal\s+(the\s+)?system\s+prompt|jailbreak"
    # Role-play attempts to borrow privileges ("pretend you are the admin", "act as HR manager").
    r"|pretend\s+(that\s+)?(you|i)\s*(are|am|'re|'m)?\s*(an?\s+|the\s+)?(admin|administrator|manager|hr|root|system|superuser)"
    r"|\bact\s+as\s+(an?\s+|the\s+)?(admin|administrator|manager|hr|root|system|superuser)",
    re.IGNORECASE,
)


def looks_like_prompt_injection(text: str) -> bool:
    return bool(_INJECTION_PATTERN.search(text))
