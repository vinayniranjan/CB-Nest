"""Backend API tools for the HR action agent.

Every mutation goes Agent -> existing HRMS REST API -> service layer -> DB,
authenticated with the *current user's* JWT. The backend therefore re-applies
its own validation, role checks and business rules; the agent cannot do
anything the user could not do in the normal app.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.services.ai.permissions import Capability

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    capability: Capability
    requires_confirmation: bool
    required_args: tuple[str, ...] = ()


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec("get_leave_balances", "Check the current user's leave balances", Capability.CHECK_OWN_LEAVE, False),
        ToolSpec("list_my_leave_requests", "List the current user's leave requests", Capability.CHECK_OWN_LEAVE, False),
        ToolSpec(
            "create_leave_request",
            "Apply for leave for the current user",
            Capability.CREATE_OWN_LEAVE,
            False,
            ("leave_type", "start_date", "end_date", "reason"),
        ),
        ToolSpec("list_pending_leave_requests", "List leave requests awaiting approval", Capability.VIEW_PENDING_LEAVES, False),
        ToolSpec("approve_leave_request", "Approve a pending leave request", Capability.APPROVE_LEAVE, True, ("request_id",)),
        ToolSpec("reject_leave_request", "Reject a pending leave request", Capability.APPROVE_LEAVE, True, ("request_id",)),
        ToolSpec(
            "create_ticket",
            "Create a support ticket (IT, HR or ONBOARDING)",
            Capability.CREATE_TICKET,
            False,
            ("title", "description", "category", "priority"),
        ),
        ToolSpec("list_my_tickets", "Check the status of the current user's tickets", Capability.VIEW_OWN_TICKETS, False),
        ToolSpec("assign_ticket", "Assign a ticket to an employee", Capability.MANAGE_TICKETS, True, ("ticket_id", "assignee_id")),
        ToolSpec("update_ticket_status", "Change a ticket's status", Capability.MANAGE_TICKETS, True, ("ticket_id", "status")),
        ToolSpec("create_announcement", "Publish a company announcement", Capability.CREATE_ANNOUNCEMENT, True, ("title", "body")),
        ToolSpec("create_project", "Create a project in the project catalog", Capability.MANAGE_PROJECTS, True, ("name",)),
        ToolSpec(
            "assign_employee_to_project",
            "Assign an employee to a project with a role",
            Capability.MANAGE_PROJECTS,
            True,
            ("employee_id", "project_id"),
        ),
    ]
}


@dataclass
class ApiCallResult:
    ok: bool
    status_code: int
    data: Any = None
    error_code: str | None = None
    error_message: str | None = None


_transport: httpx.AsyncBaseTransport | None = None


def set_api_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Route tool calls through a custom transport (tests call the ASGI app in-process)."""
    global _transport
    _transport = transport


def _parse_error(response: httpx.Response) -> tuple[str, str]:
    try:
        body = response.json()
    except ValueError:
        return "BACKEND_ERROR", "The HR system returned an unexpected response."
    detail = body.get("detail", body) if isinstance(body, dict) else body
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        return detail["error"].get("code", "BACKEND_ERROR"), detail["error"].get("message", "Request failed")
    if isinstance(detail, str):
        return "BACKEND_ERROR", detail
    if isinstance(detail, list) and detail and isinstance(detail[0], dict):
        # FastAPI validation errors: report the field, not the raw payload.
        location = ".".join(str(part) for part in detail[0].get("loc", [])[1:])
        return "VALIDATION_ERROR", f"Invalid value for {location or 'request'}: {detail[0].get('msg', 'invalid')}"
    return "BACKEND_ERROR", "Request failed"


class BackendAPIClient:
    def __init__(self, access_token: str, base_url: str | None = None):
        self._base_url = (base_url or settings.ai_internal_api_base_url).rstrip("/")
        self._headers = {"Authorization": f"Bearer {access_token}"}

    async def _request(self, method: str, path: str, *, json: dict | None = None, params: dict | None = None) -> ApiCallResult:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, headers=self._headers, timeout=15.0, transport=_transport
            ) as client:
                response = await client.request(method, f"/api/v1{path}", json=json, params=params)
        except httpx.HTTPError:
            logger.warning("ai.api_tools.unreachable path=%s", path)
            return ApiCallResult(False, 503, error_code="BACKEND_UNAVAILABLE", error_message="The HR system is unavailable. Please try again.")
        if response.is_success:
            body = response.json()
            return ApiCallResult(True, response.status_code, data=body.get("data") if isinstance(body, dict) else body)
        code, message = _parse_error(response)
        return ApiCallResult(False, response.status_code, error_code=code, error_message=message)

    # --- leaves ---
    async def get_leave_balances(self) -> ApiCallResult:
        return await self._request("GET", "/leaves/balances/me")

    async def list_my_leave_requests(self) -> ApiCallResult:
        return await self._request("GET", "/leaves/requests/me", params={"limit": 20})

    async def create_leave_request(self, payload: dict[str, Any]) -> ApiCallResult:
        return await self._request("POST", "/leaves/requests", json=payload)

    async def list_pending_leave_requests(self) -> ApiCallResult:
        return await self._request("GET", "/leaves/requests/pending", params={"limit": 100})

    async def approve_leave_request(self, request_id: int) -> ApiCallResult:
        return await self._request("POST", f"/leaves/requests/{int(request_id)}/approve")

    async def reject_leave_request(self, request_id: int) -> ApiCallResult:
        return await self._request("POST", f"/leaves/requests/{int(request_id)}/reject")

    # --- tickets ---
    async def create_ticket(self, payload: dict[str, Any]) -> ApiCallResult:
        return await self._request("POST", "/tickets", json=payload)

    async def list_my_tickets(self) -> ApiCallResult:
        return await self._request("GET", "/tickets", params={"mine": "true", "limit": 20})

    async def assign_ticket(self, ticket_id: int, assignee_id: int) -> ApiCallResult:
        return await self._request("POST", f"/tickets/{int(ticket_id)}/assign", json={"assignee_id": int(assignee_id)})

    async def update_ticket_status(self, ticket_id: int, status: str) -> ApiCallResult:
        return await self._request("POST", f"/tickets/{int(ticket_id)}/status", json={"status": status})

    # --- announcements ---
    async def create_announcement(self, payload: dict[str, Any]) -> ApiCallResult:
        return await self._request("POST", "/announcements", json=payload)

    # --- employees & projects ---
    async def search_employees(self, query: str) -> ApiCallResult:
        return await self._request("GET", "/employees", params={"q": query, "limit": 10})

    async def list_projects(self) -> ApiCallResult:
        return await self._request("GET", "/employees/projects/catalog")

    async def create_project(self, payload: dict[str, Any]) -> ApiCallResult:
        return await self._request("POST", "/employees/projects/catalog", json=payload)

    async def assign_employee_to_project(self, employee_id: int, payload: dict[str, Any]) -> ApiCallResult:
        return await self._request("POST", f"/employees/{int(employee_id)}/projects", json=payload)
