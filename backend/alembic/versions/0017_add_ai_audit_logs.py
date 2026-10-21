"""add ai audit logs and policy chunk vector store

Revision ID: 0017_add_ai_audit_logs
Revises: 0016_employee_documents_uploaded_by
Create Date: 2026-10-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_add_ai_audit_logs"
down_revision: Union[str, None] = "0016_employee_documents_uploaded_by"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=50), nullable=True),
        sa.Column("agent", sa.String(length=50), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=True),
        sa.Column("action_status", sa.String(length=30), nullable=True),
        sa.Column("records_accessed", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_ai_audit_logs_id", "ai_audit_logs", ["id"])
    op.create_index("ix_ai_audit_logs_user_id", "ai_audit_logs", ["user_id"])
    op.create_index("ix_ai_audit_logs_intent", "ai_audit_logs", ["intent"])
    op.create_index("ix_ai_audit_logs_tool_name", "ai_audit_logs", ["tool_name"])
    op.create_index("ix_ai_audit_logs_action_status", "ai_audit_logs", ["action_status"])
    op.create_index("ix_ai_audit_logs_created_at", "ai_audit_logs", ["created_at"])

    op.create_table(
        "ai_policy_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("hr_policies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("policy_checksum", sa.String(length=64), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_ai_policy_chunks_id", "ai_policy_chunks", ["id"])
    op.create_index("ix_ai_policy_chunks_policy_id", "ai_policy_chunks", ["policy_id"])
    op.create_index("ix_ai_policy_chunks_policy_checksum", "ai_policy_chunks", ["policy_checksum"])


def downgrade() -> None:
    op.drop_table("ai_policy_chunks")
    op.drop_table("ai_audit_logs")
