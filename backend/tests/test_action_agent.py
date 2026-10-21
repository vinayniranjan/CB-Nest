from datetime import date

import pytest
from jose import jwt

from app.core.config import settings
from app.services.ai.action_agent import (
    ActionPlan,
    issue_confirmation_token,
    parse_dates,
    redeem_confirmation_token,
    rule_based_plan,
)

BASE = date(2026, 10, 21)  # a Wednesday


@pytest.mark.parametrize(
    "text,expected",
    [
        ("leave for tomorrow", (date(2026, 10, 22), date(2026, 10, 22))),
        ("leave today", (BASE, BASE)),
        ("day after tomorrow", (date(2026, 10, 23), date(2026, 10, 23))),
        ("from Nov 6 to Nov 7", (date(2026, 11, 6), date(2026, 11, 7))),
        ("November 6-8", (date(2026, 11, 6), date(2026, 11, 8))),
        ("6th to 7th December", (date(2026, 12, 6), date(2026, 12, 7))),
        ("on 2026-12-24", (date(2026, 12, 24), date(2026, 12, 24))),
        ("next monday", (date(2026, 10, 26), date(2026, 10, 26))),
        ("from tomorrow for 3 days", (date(2026, 10, 22), date(2026, 10, 24))),
        ("May 6 to May 7", (date(2027, 5, 6), date(2027, 5, 7))),  # long past -> next year
        ("Oct 15", (date(2026, 10, 15), date(2026, 10, 15))),  # recent past kept (retroactive sick leave)
        ("no date here", (None, None)),
    ],
)
def test_parse_dates(text, expected):
    assert parse_dates(text, BASE) == expected


def test_leave_request_extraction():
    plan = rule_based_plan("Apply sick leave from May 6 to May 7 because I have fever.")
    assert plan.tool == "create_leave_request"
    assert plan.args["leave_type"] == "SICK"
    assert plan.args["reason"] == "I have fever"
    casual = rule_based_plan("Apply casual leave for tomorrow because of personal work.")
    assert casual.args["leave_type"] == "CASUAL" and casual.args["reason"] == "Personal work"
    assert not casual.notes
    half = rule_based_plan("Take a half day leave tomorrow afternoon")
    assert half.args["is_half_day"] is True and half.args["half_day_period"] == "SECOND_HALF"


def test_default_leave_type_is_disclosed():
    plan = rule_based_plan("Apply leave for tomorrow")
    assert plan.args["leave_type"] == "CASUAL"
    assert plan.notes


def test_ticket_extraction():
    plan = rule_based_plan("Create a high-priority IT ticket for VPN not working.")
    assert plan.tool == "create_ticket"
    assert plan.args == {
        "title": "VPN not working",
        "description": "Create a high-priority IT ticket for VPN not working",
        "category": "IT",
        "priority": "HIGH",
    }
    hr = rule_based_plan("Raise a ticket about my payslip query")
    assert hr.args["category"] == "HR" and hr.args["priority"] == "MEDIUM"


@pytest.mark.parametrize(
    "message,tool,args",
    [
        ("Approve Employee User's pending leave request.", "approve_leave_request", {"employee_name": "Employee User"}),
        ("Reject leave request #12", "reject_leave_request", {"request_id": 12}),
        ("Assign Employee User to HR Policy Copilot as AI Engineer.", "assign_employee_to_project",
         {"employee_name": "Employee User", "project_name": "HR Policy Copilot", "role_on_project": "AI Engineer"}),
        ("Create an announcement that Friday's townhall is moved to 5 PM.", "create_announcement",
         {"title": "Friday's townhall is moved to 5 PM", "body": "Friday's townhall is moved to 5 PM."}),
        ("Assign ticket #4 to Rahul Sharma", "assign_ticket", {"ticket_id": 4, "assignee_name": "Rahul Sharma"}),
        ("Mark ticket 4 as resolved", "update_ticket_status", {"ticket_id": 4, "status": "RESOLVED"}),
        ("Create a new project called Benefits Portal", "create_project", {"name": "Benefits Portal"}),
        ("Check my leave balance", "get_leave_balances", {}),
        ("What is the status of my tickets?", "list_my_tickets", {}),
    ],
)
def test_action_extraction(message, tool, args):
    plan = rule_based_plan(message)
    assert plan.tool == tool
    assert plan.args == args


def test_unrelated_message_has_no_plan():
    assert rule_based_plan("What is the capital of France?") is None


def test_confirmation_token_is_single_use_and_user_bound(users):
    plan = ActionPlan("approve_leave_request", {"request_id": 7})
    token = issue_confirmation_token(users["manager"], plan, "Approve #7?")
    assert redeem_confirmation_token(token, users["employee"]) is None  # another user
    redeemed = redeem_confirmation_token(token, users["manager"])
    assert redeemed.tool == "approve_leave_request" and redeemed.args == {"request_id": 7}
    assert redeem_confirmation_token(token, users["manager"]) is None  # replay


def test_tampered_or_expired_confirmation_rejected(users):
    plan = ActionPlan("approve_leave_request", {"request_id": 7})
    token = issue_confirmation_token(users["manager"], plan, "Approve #7?")
    claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    forged = jwt.encode({**claims, "args": {"request_id": 8}}, "wrong-secret", algorithm="HS256")
    assert redeem_confirmation_token(forged, users["manager"]) is None
    expired = jwt.encode({**claims, "jti": "x1", "exp": 1}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    assert redeem_confirmation_token(expired, users["manager"]) is None
    access_token = users["manager"].access_token  # a normal login token is not a confirmation
    assert redeem_confirmation_token(access_token, users["manager"]) is None
