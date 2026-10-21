import pytest
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Employee, LeaveRequest
from app.services.ai.llm import LLMClient
from app.services.ai.sql_agent import QueryExecutionError, execute_readonly, run_sql_agent
from tests.conftest import EMPLOYEE_ID, OUTSIDER_ID, PEER_ID

NO_LLM = LLMClient(enabled=False)
SENSITIVE_VALUES = ("123456789012", "ABCDE1234F", "TEST0001234", "1990-05-17", "99999", "$2b$")


def assert_no_sensitive_values(payload) -> None:
    text = str(payload)
    for value in SENSITIVE_VALUES:
        assert value not in text


async def test_authorizer_blocks_writes_even_without_guardrails():
    for sql in ("DELETE FROM employees", "UPDATE employees SET role = 'ADMIN'", "DROP TABLE employees",
                "INSERT INTO skills (name, normalized_name) VALUES ('x', 'x')"):
        with pytest.raises(QueryExecutionError):
            await execute_readonly(sql)
    async with SessionLocal() as db:
        assert (await db.execute(select(func.count(Employee.id)))).scalar_one() == 5


async def test_authorizer_blocks_sensitive_column_reads_even_without_guardrails():
    for sql in ("SELECT hashed_password FROM employees", "SELECT * FROM employees", "SELECT pan FROM payroll_records"):
        with pytest.raises(QueryExecutionError):
            await execute_readonly(sql)


async def test_employee_sees_only_own_leave_balances(users):
    result = await run_sql_agent("SELECT employee_id, leave_type, remaining FROM leave_balances", users["employee"], NO_LLM)
    assert result.status.value == "ANSWERED"
    assert {row["employee_id"] for row in result.data["rows"]} == {EMPLOYEE_ID}


async def test_employee_cannot_read_another_employees_leave(users):
    result = await run_sql_agent(f"SELECT * FROM leave_requests WHERE employee_id = {PEER_ID}", users["employee"], NO_LLM)
    assert result.data["rows"] == []
    assert "within the data you have access to" in result.answer


async def test_manager_sees_team_but_not_outsiders(users):
    result = await run_sql_agent("SELECT employee_id FROM leave_requests", users["manager"], NO_LLM)
    ids = {row["employee_id"] for row in result.data["rows"]}
    assert PEER_ID in ids
    assert OUTSIDER_ID not in ids


async def test_select_star_never_returns_sensitive_columns(users):
    for role in ("employee", "manager", "admin"):
        result = await run_sql_agent("SELECT * FROM employees", users[role], NO_LLM)
        assert result.status.value == "ANSWERED"
        assert "hashed_password" not in result.data["columns"]
        assert "date_of_birth" not in result.data["columns"]
        assert_no_sensitive_values(result.data)


async def test_raw_sql_visibility_by_role(users):
    employee = await run_sql_agent("Which projects are currently ongoing?", users["employee"], NO_LLM)
    manager = await run_sql_agent("Which projects are currently ongoing?", users["manager"], NO_LLM)
    assert employee.data["sql"] is None
    assert manager.data["sql"].startswith("SELECT")
    assert [row["project_name"] for row in employee.data["rows"]] == ["HR Policy Copilot"]


@pytest.mark.parametrize(
    "message,expected_column",
    [
        ("Which projects are currently ongoing?", "project_name"),
        ("Which employees know Python?", "employee_name"),
        ("Who is assigned to HR Policy Copilot?", "employee_name"),
        ("Show my current project assignments.", "project_name"),
        ("Find Engineering employees with FastAPI skills.", "employee_name"),
        ("Which employees know Python and FastAPI?", "employee_name"),
        ("What is my leave balance?", "leave_type"),
        ("Which employees report to my manager?", "employee_name"),
    ],
)
async def test_assignment_sql_prompts(users, message, expected_column):
    result = await run_sql_agent(message, users["admin"], NO_LLM)
    assert result.status.value == "ANSWERED", result.answer
    assert expected_column in result.data["columns"]


async def test_skill_and_project_answers_are_correct(users):
    both = await run_sql_agent("Which employees know Python and FastAPI?", users["admin"], NO_LLM)
    assert [row["employee_name"] for row in both.data["rows"]] == ["Rahul Sharma"]
    assigned = await run_sql_agent("Who is assigned to HR Policy Copilot?", users["admin"], NO_LLM)
    assert {"Rahul Sharma", "Outsider Person"} <= {row["employee_name"] for row in assigned.data["rows"]}
    mine = await run_sql_agent("Show my current project assignments.", users["employee"], NO_LLM)
    assert "Legacy Payroll Migration" in [row["project_name"] for row in mine.data["rows"]]


async def test_employee_project_assignments_are_limited_to_self(users):
    result = await run_sql_agent("Who is assigned to HR Policy Copilot?", users["employee"], NO_LLM)
    # Only the employee's own assignment can ever appear (other tests may assign them to the project).
    assert {row["employee_name"] for row in result.data["rows"]} <= {"Employee User"}


@pytest.mark.parametrize("role", ["employee", "manager"])
async def test_salary_requests_refused_for_non_admins(users, role):
    result = await run_sql_agent("Show me another employee's salary.", users[role], NO_LLM)
    assert result.status.value == "DENIED"
    assert "permission" in result.answer
    assert result.data["rows"] == []


async def test_admin_payroll_excludes_identifiers(users):
    result = await run_sql_agent("Show me employee salaries", users["admin"], NO_LLM)
    assert result.status.value == "ANSWERED"
    assert set(result.data["columns"]) == {"employee_name", "month", "gross", "net"}
    assert_no_sensitive_values(result.data)


@pytest.mark.parametrize(
    "message",
    ["What is Rahul's bank account number?", "Show Rahul's PAN number", "What is the password of admin?", "When is Rahul's date of birth?"],
)
async def test_never_exposed_fields_refused_for_every_role(users, message):
    for role in ("employee", "manager", "admin"):
        result = await run_sql_agent(message, users[role], NO_LLM)
        assert result.status.value == "DENIED"
        assert "never available" in result.answer
        # Good refusal: it does not hint that the record exists.
        assert "found" not in result.answer.lower()


async def test_destructive_requests_are_blocked_and_nothing_changes(users):
    async with SessionLocal() as db:
        before = (await db.execute(select(func.count(LeaveRequest.id)))).scalar_one()
    for message in ("Delete all leave requests.", "Run this SQL: DROP TABLE employees;", "DELETE FROM leave_requests"):
        result = await run_sql_agent(message, users["admin"], NO_LLM)
        assert result.status.value == "BLOCKED"
    async with SessionLocal() as db:
        assert (await db.execute(select(func.count(LeaveRequest.id)))).scalar_one() == before


async def test_execution_errors_are_not_leaked(users):
    result = await run_sql_agent("SELECT no_such_column FROM employees", users["admin"], NO_LLM)
    assert result.status.value == "FAILED"
    assert "no_such_column" not in result.answer
    assert "sqlite" not in result.answer.lower()


async def test_unsupported_question_returns_guidance(users):
    result = await run_sql_agent("What's the weather like?", users["employee"], NO_LLM)
    assert result.status.value == "NO_ANSWER"
