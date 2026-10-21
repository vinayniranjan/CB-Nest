# AI Copilot API Reference

Base URL: `http(s)://<api-host>/api/v1`. Interactive OpenAPI docs: `/docs` (Swagger) and `/redoc`.

## Authentication

Every endpoint requires the user's access token from `POST /api/v1/auth/login`:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"employee@mock-hrms.dev","password":"password123"}' | jq -r .data.access_token)
```

Send it as `Authorization: Bearer $TOKEN`. The user's identity and role are taken from this token and the database. Nothing in the request body can change them.

## Response envelope

```json
{ "success": true,  "data": { ... }, "error": null }
{ "success": false, "data": null,    "error": { "code": "RATE_LIMITED", "message": "..." } }
```

FastAPI errors raised by dependencies use `{"detail": {"success": false, "error": {...}}}`.

| HTTP | When |
|---|---|
| 200 | Request processed. Check `data.status` for the outcome; a refusal is a 200 with `status: "DENIED"` |
| 401 | Missing, invalid or expired token |
| 403 | Endpoint needs a higher role (`/chat/audit?scope=all`, `/chat/audit/stats`, `/chat/policy/reindex`) |
| 422 | Validation: `message` blank or longer than 2000 characters |
| 429 | More than `AI_RATE_LIMIT_PER_MINUTE` AI requests in a minute (default 30) |

## Chat endpoints

All four take the same body:

```json
{ "message": "string (1–2000 chars)", "confirmation_token": "string | null" }
```

| Endpoint | Purpose |
|---|---|
| `POST /chat/router` | Unified copilot: classifies the intent and routes to the right agent |
| `POST /chat/policy` | Policy RAG assistant only |
| `POST /chat/sql` | Read-only SQL agent only |
| `POST /chat/actions` | HR action agent only. Also accepts `confirmation_token` to execute a proposed action |

### Common response fields

| Field | Type | Description |
|---|---|---|
| `answer` | string | Text to show the user |
| `status` | enum | `ANSWERED`, `NO_ANSWER`, `SUCCESS`, `CONFIRMATION_REQUIRED`, `NEEDS_INPUT`, `DENIED`, `BLOCKED`, `FAILED` |
| `intent` | enum | `POLICY_QA`, `SQL_QUERY`, `HR_ACTION`, `UNKNOWN` (guardrail) |
| `confidence`, `reason` | number, string | Routing decision |
| `agent` | string | `policy_rag`, `sql_agent`, `action_agent`, `guardrail` |
| `provider` | string | `anthropic:<model>` or `rule-based` |
| `latency_ms` | int | Server processing time |

### Policy fields (`intent = POLICY_QA`)

| Field | Description |
|---|---|
| `sources[]` | `{title, category, filename}`, the policies the answer is grounded in. Empty when `NO_ANSWER` |

```bash
curl -s -X POST localhost:8000/api/v1/chat/policy -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"message":"How many sick leaves can I take?"}'
```

```json
{"success": true, "error": null, "data": {
  "answer": "You are entitled to 10 days of sick leave per year, covering illness, recovery and medical appointments.",
  "sources": [{"title": "Leave Policy", "category": "LEAVE", "filename": "seed_policy_01.md"}],
  "status": "ANSWERED", "intent": "POLICY_QA", "agent": "policy_rag", "provider": "anthropic:claude-opus-5-5", "latency_ms": 4205}}
```

### SQL fields (`intent = SQL_QUERY`)

| Field | Description |
|---|---|
| `sql` | Validated query as executed (with `LIMIT`). `null` for employees |
| `columns[]`, `rows[]` | Result set (≤ `AI_SQL_MAX_ROWS`), safe columns only |
| `row_count`, `truncated` | `truncated: true` when more rows exist than were returned |

```json
{"success": true, "error": null, "data": {
  "answer": "Found 2 results: Developer Experience Portal, HR Policy Copilot",
  "sql": null,
  "columns": ["project_name", "role_on_project", "status"],
  "rows": [{"project_name": "Developer Experience Portal", "role_on_project": "Backend Engineer", "status": "ONGOING"}],
  "row_count": 2, "truncated": false, "status": "ANSWERED", "intent": "SQL_QUERY"}}
```

Blocked and denied examples (`status` with `answer` explaining the rule):

```json
{"data": {"status": "BLOCKED", "answer": "DROP statements are not allowed. The AI assistant can only run read-only queries."}}
{"data": {"status": "DENIED",  "answer": "Passwords, bank account details, PAN details and dates of birth are never available through the AI assistant."}}
```

### Action fields (`intent = HR_ACTION`)

| Field | Description |
|---|---|
| `tool` | Backend tool chosen, e.g. `create_leave_request` |
| `args` | Arguments after name→id resolution |
| `result` | Backend API response data on `SUCCESS` |
| `confirmation` | `{token, summary, expires_in_seconds}` when `CONFIRMATION_REQUIRED` |
| `missing_fields[]` | Fields still needed when `NEEDS_INPUT` |
| `notes[]` | Assumptions made, e.g. a defaulted leave type |

Two-step confirmation:

```bash
# 1. propose
curl -s -X POST localhost:8000/api/v1/chat/actions -H "Authorization: Bearer $MANAGER_TOKEN" \
  -H 'Content-Type: application/json' -d '{"message":"Approve leave request #3"}'
# → status CONFIRMATION_REQUIRED, confirmation.token = "<jwt>"

# 2. confirm (single use, same user, within 5 minutes)
curl -s -X POST localhost:8000/api/v1/chat/actions -H "Authorization: Bearer $MANAGER_TOKEN" \
  -H 'Content-Type: application/json' -d '{"message":"confirm","confirmation_token":"<jwt>"}'
# → status SUCCESS, answer "Leave request #3 has been approved."
```

| Tool | Backend API called | Roles | Confirmation |
|---|---|---|---|
| `create_leave_request` | `POST /leaves/requests` | all | no |
| `get_leave_balances` | `GET /leaves/balances/me` | all | no |
| `list_my_leave_requests` | `GET /leaves/requests/me` | all | no |
| `list_pending_leave_requests` | `GET /leaves/requests/pending` | manager, admin | no |
| `approve_leave_request` / `reject_leave_request` | `POST /leaves/requests/{id}/approve` · `/reject` | manager, admin | yes |
| `create_ticket` | `POST /tickets` | all | no |
| `list_my_tickets` | `GET /tickets?mine=true` | all | no |
| `assign_ticket` | `POST /tickets/{id}/assign` | manager, admin | yes |
| `update_ticket_status` | `POST /tickets/{id}/status` | manager, admin | yes |
| `create_announcement` | `POST /announcements` | manager, admin | yes |
| `create_project` | `POST /employees/projects/catalog` | manager, admin | yes |
| `assign_employee_to_project` | `POST /employees/{id}/projects` | manager, admin | yes |

## Supporting endpoints

| Endpoint | Roles | Returns |
|---|---|---|
| `GET /chat/capabilities` | all | `{role, mode, capabilities[], suggestions[], provider}`, used by the UI for role-aware behaviour |
| `GET /chat/audit?limit=20&scope=me` | all (`scope=all`: admin) | `{items: [{id, user_id, role, message (redacted), intent, agent, tool_name, action_status, records_accessed, latency_ms, created_at}]}` |
| `GET /chat/audit/stats` | admin | `{total_requests, requests_by_intent, requests_by_status, tool_usage, permission_denied, sql_blocked, rag_no_answer_rate, avg_latency_ms}` |
| `POST /chat/policy/reindex` | manager, admin | `{policies, reindexed_policies, removed}` |
| `GET /health` · `GET /api/v1/health` | public | `{status: "ok"}` |

The legacy `POST /chat/sessions` and `/chat/sessions/{id}/messages` stubs still return `501`, which keeps the original contract intact.
