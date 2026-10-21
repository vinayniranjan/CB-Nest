"""SQL guardrails for the HR intelligence agent.

Defence in depth, applied to every query (LLM-generated or user-typed):

1. Keyword screen: DDL/DML/PRAGMA/ATTACH... are rejected before parsing.
2. AST validation (sqlglot): exactly one statement, read-only SELECT/UNION only,
   allow-listed tables per role, no schema-qualified tables, no forbidden
   columns, no dangerous functions.
3. Row-level + column-level scoping: every referenced HR table is shadowed by a
   CTE of the same name that exposes only safe columns and only rows the role may
   see. A query cannot "forget" a filter, because the unfiltered table is not
   reachable by name.
4. Row limit enforced in the SQL and again when fetching.
5. Execution on a separate read-only SQLite connection with ``query_only`` and an
   authorizer that denies writes and reads of sensitive columns (see sql_agent).
"""

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.models.enums import Role
from app.services.ai.context import UserContext

FORBIDDEN_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE", "TRUNCATE",
    "PRAGMA", "ATTACH", "DETACH", "VACUUM", "REINDEX", "GRANT", "REVOKE", "UPSERT",
)
_FORBIDDEN_KEYWORD_PATTERN = re.compile(r"\b(" + "|".join(FORBIDDEN_KEYWORDS) + r")\b", re.IGNORECASE)
_STRING_LITERAL_PATTERN = re.compile(r"'(?:[^']|'')*'")

FORBIDDEN_COLUMNS = frozenset(
    {
        "hashed_password",
        "bank_name",
        "bank_account_number",
        "bank_account_name",
        "bank_branch",
        "bank_ifsc",
        "pan_number",
        "pan_name",
        "pan_dob",
        "date_of_birth",
        "current_salary_usd",
        "profile_photo_path",
        "profile_photo_mime",
        # payroll_records identifiers
        "pan",
        "pf_uan",
        "esi_no",
    }
)

FORBIDDEN_FUNCTIONS = frozenset(
    {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer", "randomblob", "zeroblob", "sqlite_offset"}
)

_EMPLOYEE_COLUMNS = "id, name, email, department_id, manager_id, role, status, joining_date, occupancy"
_EMPLOYEE_COLUMNS_ADMIN = _EMPLOYEE_COLUMNS + ", phone, address, blood_type"

# Column lists for the LLM schema prompt (what each scoped view exposes).
TABLE_COLUMNS: dict[str, str] = {
    "employees": _EMPLOYEE_COLUMNS,
    "departments": "id, name, location",
    "projects": "id, name, description, status (ONGOING|COMPLETED|ON_HOLD|PLANNED)",
    "employee_projects": "id, employee_id, project_id, role_on_project",
    "skills": "id, name, normalized_name",
    "employee_skills": "id, employee_id, skill_id, level (BEGINNER|INTERMEDIATE|EXPERT)",
    "job_history": "id, employee_id, designation, business_unit, department, start_date, end_date, is_current",
    "leave_balances": "id, employee_id, leave_type (CASUAL|SICK|EARNED), total, used, remaining",
    "leave_requests": "id, employee_id, leave_type, start_date, end_date, reason, is_half_day, half_day_period, "
    "status (PENDING|APPROVED|REJECTED), approver_id",
    "tickets": "id, employee_id, assignee_id, title, description, category (IT|HR|ONBOARDING), "
    "priority (LOW|MEDIUM|HIGH), status (OPEN|IN_PROGRESS|RESOLVED), created_at",
    "payroll_records": "id, employee_id, month, gross, net",
}

PUBLIC_TABLES = ("departments", "projects", "skills", "employee_skills")
PERSONAL_TABLES = ("job_history", "leave_balances", "leave_requests")
ROLE_TABLES: dict[Role, frozenset[str]] = {
    Role.EMPLOYEE: frozenset({"employees", "employee_projects", "tickets", *PUBLIC_TABLES, *PERSONAL_TABLES}),
    Role.MANAGER: frozenset({"employees", "employee_projects", "tickets", *PUBLIC_TABLES, *PERSONAL_TABLES}),
    Role.ADMIN: frozenset({"employees", "employee_projects", "tickets", "payroll_records", *PUBLIC_TABLES, *PERSONAL_TABLES}),
}


class SQLGuardrailError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ValidatedQuery:
    display_sql: str  # the validated query (with LIMIT) as shown to permitted roles
    executable_sql: str  # display_sql wrapped in role-scoping CTEs
    tables: tuple[str, ...]


def _scope_sql(table: str, user: UserContext) -> str:
    """SELECT that defines what ``table`` means for this user. ``user.user_id`` is a server-side int."""
    uid = int(user.user_id)
    role = user.role
    team = f"SELECT id FROM main.employees WHERE manager_id = {uid}"
    if table == "employees":
        columns = _EMPLOYEE_COLUMNS_ADMIN if role == Role.ADMIN else _EMPLOYEE_COLUMNS
        where = "" if role == Role.ADMIN else f" WHERE status = 'ACTIVE' OR id = {uid}"
        return f"SELECT {columns} FROM main.employees{where}"
    if table in PUBLIC_TABLES:
        return f"SELECT * FROM main.{table}"
    if table == "payroll_records":
        return "SELECT id, employee_id, month, gross, net FROM main.payroll_records"
    if role == Role.ADMIN:
        return f"SELECT * FROM main.{table}"
    own = f"employee_id = {uid}"
    team_filter = f"{own} OR employee_id IN ({team})" if role == Role.MANAGER else own
    if table == "tickets":
        return f"SELECT * FROM main.tickets WHERE {team_filter} OR assignee_id = {uid}"
    if table in {"employee_projects", *PERSONAL_TABLES}:
        return f"SELECT * FROM main.{table} WHERE {team_filter}"
    raise SQLGuardrailError("TABLE_NOT_ALLOWED", f"Table '{table}' is not available to the AI assistant.")


def _strip(sql: str) -> str:
    cleaned = sql.strip()
    cleaned = re.sub(r"^```(?:sql)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()
    while cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()
    return cleaned


def validate_and_scope(sql: str, user: UserContext, max_rows: int) -> ValidatedQuery:
    cleaned = _strip(sql)
    if not cleaned:
        raise SQLGuardrailError("EMPTY_QUERY", "No SQL query was produced.")
    if "--" in cleaned or "/*" in cleaned:
        raise SQLGuardrailError("COMMENTS_NOT_ALLOWED", "SQL comments are not allowed.")

    without_literals = _STRING_LITERAL_PATTERN.sub("''", cleaned)
    if ";" in without_literals:
        raise SQLGuardrailError("MULTIPLE_STATEMENTS", "Only a single SQL statement is allowed.")
    keyword = _FORBIDDEN_KEYWORD_PATTERN.search(without_literals)
    if keyword:
        raise SQLGuardrailError(
            "WRITE_OPERATION_BLOCKED",
            f"{keyword.group(1).upper()} statements are not allowed. The AI assistant can only run read-only queries.",
        )

    try:
        statements = [s for s in sqlglot.parse(cleaned, read="sqlite") if s is not None]
    except ParseError as exc:
        raise SQLGuardrailError("INVALID_SQL", "The query could not be parsed as valid SQL.") from exc
    if len(statements) != 1:
        raise SQLGuardrailError("MULTIPLE_STATEMENTS", "Only a single SQL statement is allowed.")
    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.SetOperation)):
        raise SQLGuardrailError("NOT_A_SELECT", "Only SELECT queries are allowed.")
    for node_type in (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Pragma):
        if statement.find(node_type) is not None:
            raise SQLGuardrailError("WRITE_OPERATION_BLOCKED", "Only read-only SELECT queries are allowed.")

    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    allowed_tables = ROLE_TABLES[user.role]
    clash = cte_names & set(TABLE_COLUMNS)
    if clash:
        raise SQLGuardrailError("CTE_NAME_NOT_ALLOWED", f"CTE names may not shadow HR tables ({', '.join(sorted(clash))}).")

    referenced: set[str] = set()
    for table in statement.find_all(exp.Table):
        name = table.name.lower()
        if table.args.get("db") or table.args.get("catalog"):
            raise SQLGuardrailError("TABLE_NOT_ALLOWED", "Schema-qualified table names are not allowed.")
        if name in cte_names:
            continue
        if name not in allowed_tables:
            if name == "payroll_records":
                raise SQLGuardrailError(
                    "PERMISSION_DENIED", "You do not have permission to view payroll or salary information."
                )
            raise SQLGuardrailError("TABLE_NOT_ALLOWED", f"Table '{name}' is not available to the AI assistant.")
        referenced.add(name)
    if not referenced and not cte_names:
        raise SQLGuardrailError("NO_TABLES", "The query must read from an HR table.")

    for column in statement.find_all(exp.Column):
        if column.name.lower() in FORBIDDEN_COLUMNS:
            raise SQLGuardrailError(
                "SENSITIVE_COLUMN",
                "That query requests sensitive fields (passwords, bank, PAN, date of birth or salary), "
                "which are never available through the AI assistant.",
            )
    for func in statement.find_all(exp.Func):
        func_name = (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()
        if func_name in FORBIDDEN_FUNCTIONS:
            raise SQLGuardrailError("FUNCTION_NOT_ALLOWED", f"Function '{func_name}' is not allowed.")

    limit = statement.args.get("limit")
    limit_value = None
    if isinstance(limit, exp.Limit) and isinstance(limit.expression, exp.Literal) and limit.expression.is_int:
        limit_value = int(limit.expression.this)
    limit_imposed = limit_value is None or limit_value > max_rows
    if limit_imposed:
        statement.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
    display_sql = statement.sql(dialect="sqlite")

    scoped = statement.copy()
    if limit_imposed:
        # One extra row lets the executor tell the user the result was truncated.
        scoped.set("limit", exp.Limit(expression=exp.Literal.number(max_rows + 1)))
    scope_ctes = [
        exp.CTE(
            this=sqlglot.parse_one(_scope_sql(name, user), read="sqlite"),
            alias=exp.TableAlias(this=exp.to_identifier(name)),
        )
        for name in sorted(referenced)
    ]
    with_key = _with_arg_key(scoped)
    existing_with = scoped.args.get(with_key)
    if existing_with is not None:
        if existing_with.args.get("recursive"):
            raise SQLGuardrailError("RECURSIVE_NOT_ALLOWED", "Recursive queries are not allowed.")
        existing_with.set("expressions", scope_ctes + list(existing_with.expressions))
    elif scope_ctes:
        scoped.set(with_key, exp.With(expressions=scope_ctes))
    executable_sql = scoped.sql(dialect="sqlite")
    _assert_scoped(executable_sql, referenced)
    return ValidatedQuery(display_sql=display_sql, executable_sql=executable_sql, tables=tuple(sorted(referenced)))


def _with_arg_key(node: exp.Expression) -> str:
    # sqlglot renamed the WITH arg from "with" to "with_" in newer releases.
    return "with_" if "with_" in type(node).arg_types else "with"


def _assert_scoped(executable_sql: str, referenced: set[str]) -> None:
    """Fail closed: refuse to run unless every referenced HR table is shadowed by its scoping CTE."""
    parsed = sqlglot.parse_one(executable_sql, read="sqlite")
    top_with = parsed.args.get(_with_arg_key(parsed))
    scoped_names = {cte.alias_or_name.lower() for cte in top_with.expressions} if top_with is not None else set()
    if not referenced <= scoped_names:
        raise SQLGuardrailError("SCOPING_FAILED", "The query could not be safely scoped to your permissions.")


def schema_description(role: Role) -> str:
    """Role-scoped schema shown to the LLM: only tables/columns this role may query."""
    lines = [f"- {table}({TABLE_COLUMNS[table]})" for table in sorted(ROLE_TABLES[role])]
    return "\n".join(lines)
