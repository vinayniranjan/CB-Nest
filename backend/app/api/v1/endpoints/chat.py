from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import error_response, success_response
from app.db.session import get_db
from app.models.employee import Employee
from app.models.enums import Role
from app.schemas.chat import AIChatRequest, ChatMessageCreate, ChatSessionCreate
from app.services.ai.audit import audit_stats, list_audit_logs
from app.services.ai.context import UserContext
from app.services.ai.llm import get_llm
from app.services.ai.orchestrator import handle_message
from app.services.ai.permissions import ROLE_CAPABILITIES, Capability, has_capability, refusal_for
from app.services.ai.policy_rag import ensure_index
from app.services.ai.rate_limit import ai_rate_limiter
from app.services.ai.types import Intent
from app.services.auth import get_current_user, oauth2_scheme, require_roles

router = APIRouter()


async def get_user_context(
    token: str = Depends(oauth2_scheme),
    current_user: Employee = Depends(get_current_user),
) -> UserContext:
    """Identity and role come from the verified JWT, never from the request body."""
    if not ai_rate_limiter.allow(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_response("RATE_LIMITED", "Too many AI requests. Please wait a minute and try again."),
        )
    return UserContext.from_employee(current_user, token)


async def _chat(payload: AIChatRequest, user: UserContext, db: AsyncSession, intent: Intent | None):
    data = await handle_message(
        db=db,
        user=user,
        message=payload.message,
        llm=get_llm(),
        forced_intent=intent,
        confirmation_token=payload.confirmation_token,
    )
    return success_response(data)


@router.post("/policy")
async def chat_policy(payload: AIChatRequest, user: UserContext = Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    """Policy RAG assistant: grounded answers with policy sources."""
    return await _chat(payload, user, db, Intent.POLICY_QA)


@router.post("/sql")
async def chat_sql(payload: AIChatRequest, user: UserContext = Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    """Read-only SQL agent over HR data, scoped to the caller's role."""
    return await _chat(payload, user, db, Intent.SQL_QUERY)


@router.post("/actions")
async def chat_actions(payload: AIChatRequest, user: UserContext = Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    """HR task automation through existing backend APIs (with confirmation for high-impact actions)."""
    return await _chat(payload, user, db, Intent.HR_ACTION)


@router.post("/router")
async def chat_router(payload: AIChatRequest, user: UserContext = Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    """Unified copilot: classifies the intent and routes to the right assistant."""
    return await _chat(payload, user, db, None)


_ROLE_MODES = {
    Role.EMPLOYEE: (
        "Employee Copilot",
        ["How many sick leaves can I take?", "Show my current project assignments.", "Create a high-priority IT ticket for VPN not working.", "Apply casual leave for tomorrow because of personal work."],
    ),
    Role.MANAGER: (
        "Manager Copilot",
        ["Show pending leave requests.", "Which employees know Python and FastAPI?", "Approve Employee User's pending leave request.", "Create an announcement that Friday's townhall is moved to 5 PM."],
    ),
    Role.ADMIN: (
        "Admin Copilot",
        ["Who is assigned to HR Policy Copilot?", "Assign Employee User to HR Policy Copilot as AI Engineer.", "Find Engineering employees with FastAPI skills.", "Create an announcement that Friday's townhall is moved to 5 PM."],
    ),
}


@router.get("/capabilities")
async def chat_capabilities(current_user: Employee = Depends(get_current_user)):
    mode, suggestions = _ROLE_MODES[current_user.role]
    llm = get_llm()
    return success_response(
        {
            "role": current_user.role.value,
            "mode": mode,
            "capabilities": sorted(c.value for c in ROLE_CAPABILITIES[current_user.role]),
            "suggestions": suggestions,
            "provider": llm.provider_name,
        }
    )


@router.get("/audit")
async def chat_audit(
    limit: int = Query(default=20, ge=1, le=100),
    scope: str = Query(default="me", pattern="^(me|all)$"),
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recent AI actions: your own, or everyone's for admins (scope=all)."""
    if scope == "all" and not has_capability(current_user.role, Capability.VIEW_AUDIT_ALL):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error_response("FORBIDDEN", refusal_for(Capability.VIEW_AUDIT_ALL)))
    user_id = None if scope == "all" else current_user.id
    return success_response({"items": await list_audit_logs(db, user_id=user_id, limit=limit)})


@router.get("/audit/stats")
async def chat_audit_stats(
    _: Employee = Depends(require_roles(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """AI usage dashboard metrics (admin only)."""
    return success_response(await audit_stats(db))


@router.post("/policy/reindex")
async def chat_policy_reindex(
    _: Employee = Depends(require_roles(Role.ADMIN, Role.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Re-sync the policy vector store (also happens automatically before each policy question)."""
    return success_response(await ensure_index(db))


# --- Legacy Phase-3 session stubs, kept for contract compatibility ---

@router.post("/sessions")
async def create_chat_session(
    payload: ChatSessionCreate,
    current_user: Employee = Depends(get_current_user),
):
    _ = payload
    _ = current_user
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=error_response("CHAT_NOT_IMPLEMENTED", "Use /api/v1/chat/router, /policy, /sql or /actions"),
    )


@router.post("/sessions/{session_id}/messages")
async def post_chat_message(
    session_id: str,
    payload: ChatMessageCreate,
    current_user: Employee = Depends(get_current_user),
):
    _ = session_id
    _ = payload
    _ = current_user
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=error_response("CHAT_NOT_IMPLEMENTED", "Use /api/v1/chat/router, /policy, /sql or /actions"),
    )
