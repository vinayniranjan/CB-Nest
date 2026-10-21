import json
import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_audit_log import AIAuditLog
from app.services.ai.context import UserContext

logger = logging.getLogger(__name__)

MAX_LOGGED_MESSAGE_CHARS = 2000

_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bBearer\s+\S+", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]+"), "[REDACTED_KEY]"),
    (re.compile(r"(password|passwd|pwd)\s*[:=]?\s*\S+", re.IGNORECASE), r"\1 [REDACTED]"),
    (re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"), "[REDACTED_PAN]"),
    (re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"), "[REDACTED_IFSC]"),
    (re.compile(r"\b\d{9,18}\b"), "[REDACTED_NUMBER]"),
]


def redact(text: str) -> str:
    """Strip secrets and identifiers (JWTs, passwords, PAN, IFSC, account numbers) before logging."""
    redacted = text
    for pattern, replacement in _REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    if len(redacted) > MAX_LOGGED_MESSAGE_CHARS:
        redacted = redacted[:MAX_LOGGED_MESSAGE_CHARS] + "…"
    return redacted


async def write_audit_log(
    db: AsyncSession,
    *,
    user: UserContext,
    message: str,
    intent: str | None,
    agent: str | None,
    tool_name: str | None,
    action_status: str,
    records_accessed: dict[str, Any] | None = None,
    latency_ms: int | None = None,
) -> None:
    """Persist an audit row. Failures are logged, never raised: auditing must not break the user flow."""
    try:
        db.add(
            AIAuditLog(
                user_id=user.user_id,
                role=user.role.value,
                message=redact(message),
                intent=intent,
                agent=agent,
                tool_name=tool_name,
                action_status=action_status,
                records_accessed=json.dumps(records_accessed, default=str) if records_accessed else None,
                latency_ms=latency_ms,
            )
        )
        await db.commit()
    except Exception:  # noqa: BLE001 - audit must never take the request down
        await db.rollback()
        logger.exception("ai.audit.write_failed")


def _audit_payload(row: AIAuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "role": row.role,
        "message": row.message,
        "intent": row.intent,
        "agent": row.agent,
        "tool_name": row.tool_name,
        "action_status": row.action_status,
        "records_accessed": json.loads(row.records_accessed) if row.records_accessed else None,
        "latency_ms": row.latency_ms,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_audit_logs(db: AsyncSession, *, user_id: int | None, limit: int) -> list[dict[str, Any]]:
    query = select(AIAuditLog).order_by(AIAuditLog.id.desc()).limit(limit)
    if user_id is not None:
        query = query.where(AIAuditLog.user_id == user_id)
    rows = (await db.execute(query)).scalars().all()
    return [_audit_payload(row) for row in rows]


async def audit_stats(db: AsyncSession) -> dict[str, Any]:
    total = (await db.execute(select(func.count(AIAuditLog.id)))).scalar_one()
    avg_latency = (await db.execute(select(func.avg(AIAuditLog.latency_ms)))).scalar_one()

    async def _grouped(column) -> dict[str, int]:
        rows = (await db.execute(select(column, func.count(AIAuditLog.id)).group_by(column))).all()
        return {str(key): count for key, count in rows if key is not None}

    by_status = await _grouped(AIAuditLog.action_status)
    by_intent = await _grouped(AIAuditLog.intent)
    by_tool = await _grouped(AIAuditLog.tool_name)
    policy_total = by_intent.get("POLICY_QA", 0)
    no_answer = (
        await db.execute(
            select(func.count(AIAuditLog.id)).where(
                AIAuditLog.intent == "POLICY_QA", AIAuditLog.action_status == "NO_ANSWER"
            )
        )
    ).scalar_one()
    return {
        "total_requests": total,
        "requests_by_intent": by_intent,
        "requests_by_status": by_status,
        "tool_usage": by_tool,
        "permission_denied": by_status.get("DENIED", 0),
        "sql_blocked": by_status.get("BLOCKED", 0),
        "rag_no_answer_rate": round(no_answer / policy_total, 3) if policy_total else 0.0,
        "avg_latency_ms": round(float(avg_latency), 1) if avg_latency is not None else None,
    }
