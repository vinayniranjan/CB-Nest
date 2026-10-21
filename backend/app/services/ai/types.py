import enum
from dataclasses import dataclass, field
from typing import Any


class Intent(str, enum.Enum):
    POLICY_QA = "POLICY_QA"
    SQL_QUERY = "SQL_QUERY"
    HR_ACTION = "HR_ACTION"
    UNKNOWN = "UNKNOWN"


class Status(str, enum.Enum):
    ANSWERED = "ANSWERED"
    NO_ANSWER = "NO_ANSWER"
    SUCCESS = "SUCCESS"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    NEEDS_INPUT = "NEEDS_INPUT"
    DENIED = "DENIED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


@dataclass
class AgentResult:
    """Uniform result of any agent; ``data`` is what the API returns to the client."""

    intent: Intent
    agent: str
    status: Status
    answer: str
    data: dict[str, Any] = field(default_factory=dict)
    tool_name: str | None = None
    # Record identifiers touched, for the audit log (never record contents).
    records_accessed: dict[str, Any] | None = None
