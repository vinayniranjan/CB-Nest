import pytest

from app.models.enums import Role
from app.services.ai.context import UserContext
from app.services.ai.sql_guardrails import SQLGuardrailError, schema_description, validate_and_scope

EMPLOYEE = UserContext(3, "Employee User", Role.EMPLOYEE, 1, 2, "t")
MANAGER = UserContext(2, "Manager User", Role.MANAGER, 3, None, "t")
ADMIN = UserContext(1, "Admin User", Role.ADMIN, 2, None, "t")


def blocked(sql: str, user: UserContext = EMPLOYEE) -> str:
    with pytest.raises(SQLGuardrailError) as exc:
        validate_and_scope(sql, user, max_rows=100)
    return exc.value.code


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO tickets (title) VALUES ('x')",
        "UPDATE employees SET role = 'ADMIN'",
        "DELETE FROM leave_requests",
        "DROP TABLE employees",
        "ALTER TABLE employees ADD COLUMN x TEXT",
        "CREATE TABLE x (id INT)",
        "REPLACE INTO skills (id, name) VALUES (1, 'x')",
        "TRUNCATE TABLE tickets",
        "PRAGMA table_info(employees)",
        "ATTACH DATABASE 'x.db' AS x",
        "DETACH DATABASE x",
    ],
)
def test_every_write_or_admin_statement_is_blocked(sql):
    assert blocked(sql) == "WRITE_OPERATION_BLOCKED"


def test_write_keyword_hidden_after_select_is_blocked():
    assert blocked("SELECT * FROM employees; DROP TABLE employees") in {"MULTIPLE_STATEMENTS", "WRITE_OPERATION_BLOCKED"}
    assert blocked("SELECT 1 FROM employees; SELECT 2 FROM employees") == "MULTIPLE_STATEMENTS"


def test_comments_are_rejected():
    assert blocked("SELECT name FROM employees -- WHERE id = 3") == "COMMENTS_NOT_ALLOWED"
    assert blocked("SELECT name /* x */ FROM employees") == "COMMENTS_NOT_ALLOWED"


@pytest.mark.parametrize("column", ["hashed_password", "bank_account_number", "pan_number", "date_of_birth", "current_salary_usd", "bank_ifsc"])
def test_sensitive_columns_are_blocked_for_every_role(column):
    for user in (EMPLOYEE, MANAGER, ADMIN):
        assert blocked(f"SELECT name, {column} FROM employees", user) == "SENSITIVE_COLUMN"


def test_internal_and_qualified_tables_are_blocked():
    assert blocked("SELECT * FROM sqlite_master") == "TABLE_NOT_ALLOWED"
    assert blocked("SELECT * FROM main.employees") == "TABLE_NOT_ALLOWED"
    assert blocked("SELECT * FROM ai_audit_logs", ADMIN) == "TABLE_NOT_ALLOWED"


def test_payroll_is_admin_only():
    assert blocked("SELECT * FROM payroll_records", EMPLOYEE) == "PERMISSION_DENIED"
    assert blocked("SELECT * FROM payroll_records", MANAGER) == "PERMISSION_DENIED"
    assert validate_and_scope("SELECT gross FROM payroll_records", ADMIN, 100).tables == ("payroll_records",)


def test_payroll_identifiers_blocked_even_for_admin():
    assert blocked("SELECT pan FROM payroll_records", ADMIN) == "SENSITIVE_COLUMN"


def test_dangerous_functions_are_blocked():
    assert blocked("SELECT load_extension('evil') FROM employees") == "FUNCTION_NOT_ALLOWED"


def test_cte_cannot_shadow_hr_tables():
    assert blocked("WITH employees AS (SELECT 1 AS id) SELECT * FROM employees") == "CTE_NAME_NOT_ALLOWED"


def test_unparseable_sql_is_rejected():
    assert blocked("SELECT FROM WHERE") == "INVALID_SQL"


def test_row_limit_is_enforced():
    validated = validate_and_scope("SELECT name FROM employees LIMIT 5000", EMPLOYEE, max_rows=100)
    assert "LIMIT 100" in validated.display_sql
    assert "LIMIT 101" in validated.executable_sql  # one extra row detects truncation
    small = validate_and_scope("SELECT name FROM employees LIMIT 5", EMPLOYEE, max_rows=100)
    assert "LIMIT 5" in small.executable_sql


def test_employee_queries_are_scoped_to_own_rows():
    validated = validate_and_scope("SELECT * FROM leave_balances", EMPLOYEE, 100)
    assert validated.executable_sql.startswith("WITH leave_balances AS")
    assert "employee_id = 3" in validated.executable_sql
    assert "hashed_password" not in validated.executable_sql


def test_manager_scope_includes_team():
    validated = validate_and_scope("SELECT * FROM leave_requests", MANAGER, 100)
    assert "manager_id = 2" in validated.executable_sql


def test_admin_employee_view_still_excludes_sensitive_columns():
    validated = validate_and_scope("SELECT * FROM employees", ADMIN, 100)
    for column in ("hashed_password", "bank_account_number", "pan_number", "date_of_birth", "current_salary_usd"):
        assert column not in validated.executable_sql


def test_user_ctes_and_unions_are_scoped():
    validated = validate_and_scope(
        "WITH mine AS (SELECT project_id FROM employee_projects) SELECT name FROM projects WHERE id IN (SELECT project_id FROM mine)",
        EMPLOYEE,
        100,
    )
    assert validated.executable_sql.startswith("WITH employee_projects AS")
    union = validate_and_scope("SELECT name FROM employees UNION SELECT name FROM projects", EMPLOYEE, 100)
    assert "WITH employees AS" in union.executable_sql


def test_string_literals_do_not_trigger_keyword_block():
    validated = validate_and_scope("SELECT name FROM projects WHERE name = 'Drop Zone'", EMPLOYEE, 100)
    assert validated.tables == ("projects",)


def test_schema_description_is_role_scoped():
    assert "payroll_records" not in schema_description(Role.EMPLOYEE)
    assert "payroll_records" in schema_description(Role.ADMIN)
    assert "hashed_password" not in schema_description(Role.ADMIN)
