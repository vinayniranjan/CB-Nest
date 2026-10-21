# AI Permissions Matrix

Authorization is enforced in the backend at three levels: the AI capability check (`app/services/ai/permissions.py`), SQL row/column scoping (`app/services/ai/sql_guardrails.py`), and the existing HRMS API role checks, which every AI action goes through. The frontend only *displays* role information; it enforces nothing.

## Matrix

| AI capability | Employee | Manager | Admin | Enforced by | Test |
|---|:---:|:---:|:---:|---|---|
| Ask HR policy questions | ✅ | ✅ | ✅ | `POLICY_QA` capability | `test_policy_rag.py` |
| Ask own leave balance | ✅ | ✅ | ✅ | `GET /leaves/balances/me` (own token) · SQL scope | `test_leave_balance_via_api` |
| Ask another employee's leave balance | ❌ | Team only | ✅ | SQL scope: `employee_id = me` / `me + direct reports` | `test_employee_cannot_read_another_employees_leave`, `test_manager_sees_team_but_not_outsiders` |
| View own project assignments | ✅ | ✅ | ✅ | SQL scope on `employee_projects` | `test_skill_and_project_answers_are_correct` |
| View all project assignments | ❌ (own only) | Limited (self + team) | ✅ | SQL scope on `employee_projects` | `test_employee_project_assignments_are_limited_to_self` |
| Search employees by skill | Limited (directory fields only) | ✅ | ✅ | Scoped `employees` view exposes directory columns only | `test_select_star_never_returns_sensitive_columns` |
| Generate SQL over HR data | Limited | Limited | ✅ | Role table allow-list + scoping CTEs | `test_sql_guardrails.py` |
| View raw SQL | ❌ | ✅ | ✅ | `VIEW_RAW_SQL` capability (`sql` = `null` for employees) | `test_raw_sql_visibility_by_role` |
| Create own leave request | ✅ | ✅ | ✅ | `POST /leaves/requests` with the user's token | `test_employee_applies_for_leave_via_backend_api` |
| Approve / reject leave | ❌ | ✅ | ✅ | `APPROVE_LEAVE` capability → confirmation → backend role check | `test_employee_cannot_approve_leave_and_nothing_changes`, `test_manager_approval_requires_confirmation` |
| Create ticket | ✅ | ✅ | ✅ | `POST /tickets` | `test_ticket_creation` |
| Assign / update ticket | ❌ | ✅ | ✅ | `MANAGE_TICKETS` capability | `test_employee_cannot_assign_or_update_tickets` |
| Create announcement | ❌ | ✅ | ✅ | `CREATE_ANNOUNCEMENT` capability → confirmation | `test_announcement_flow_and_denial` |
| Assign employee to project | ❌ | ✅ | ✅ | `MANAGE_PROJECTS` capability → confirmation | `test_project_assignment_admin_only_flow` |
| Access payroll data | ❌ (blocked; own payslips via Finance page) | ❌ | ✅ (`gross`, `net`, `month` only) | `payroll_records` admin-only table; `pan`, `pf_uan`, `esi_no` never selectable | `test_salary_requests_refused_for_non_admins`, `test_admin_payroll_excludes_identifiers` |
| Access bank / PAN / password / DOB fields | ❌ | ❌ | ❌ | Refused before querying; columns absent from scoped views; SQLite authorizer denies reads | `test_never_exposed_fields_refused_for_every_role`, `test_authorizer_blocks_sensitive_column_reads_even_without_guardrails` |
| View AI audit log | Own | Own | All + usage stats | `VIEW_AUDIT_ALL` capability / admin-only stats | `test_audit_visibility` |

## Column policy

Never returned by the AI, for any role: `hashed_password`, `bank_name`, `bank_account_number`, `bank_account_name`, `bank_branch`, `bank_ifsc`, `pan_number`, `pan_name`, `pan_dob`, `date_of_birth`, `current_salary_usd`, `profile_photo_path`, `profile_photo_mime`, and payroll `pan`, `pf_uan`, `esi_no`.

`employees` as seen by the SQL agent:

| Role | Columns | Rows |
|---|---|---|
| Employee / Manager | `id, name, email, department_id, manager_id, role, status, joining_date, occupancy` | active employees + self |
| Admin | the above + `phone, address, blood_type` | all |

## Row scopes (CTE shadowing)

| Table | Employee | Manager | Admin |
|---|---|---|---|
| `departments`, `projects`, `skills`, `employee_skills` | all | all | all |
| `employee_projects`, `job_history`, `leave_balances`, `leave_requests` | own rows | own + direct reports | all |
| `tickets` | raised by or assigned to me | + raised by direct reports | all |
| `payroll_records` | — (blocked) | — (blocked) | all (`gross`, `net`, `month`) |

## Refusal wording

Refusals state the rule without confirming that data exists:

- "You do not have permission to approve or reject leave requests."
- "You do not have permission to view payroll or salary information through the AI assistant. You can view your own payslips on the Finance page."
- "Passwords, bank account details, PAN details and dates of birth are never available through the AI assistant."
- Scoped queries that match nothing outside your access return "No matching records found within the data you have access to."
