from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AIAuditLog(Base):
    """One row per AI copilot interaction. Messages are redacted before storage."""

    __tablename__ = "ai_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    agent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    action_status: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    records_accessed: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False, index=True
    )
