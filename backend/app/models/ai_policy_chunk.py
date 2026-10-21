from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AIPolicyChunk(Base):
    """Retrieval chunk of an HR policy document with its embedding (the local vector store)."""

    __tablename__ = "ai_policy_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("hr_policies.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(220))
    category: Mapped[str] = mapped_column(String(60))
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    policy_checksum: Mapped[str] = mapped_column(String(64), index=True)
    embedding: Mapped[list[float]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
