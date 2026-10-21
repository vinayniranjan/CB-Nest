from typing import Any

import pytest

from app.core.config import Settings
from app.services.ai.audit import redact
from app.services.ai.llm import LLMClient
from app.services.ai.orchestrator import classify
from app.services.ai.policy_rag import answer_policy_question
from app.services.ai.sql_agent import run_sql_agent
from app.services.ai.action_agent import run_action_agent
from app.db.session import SessionLocal


class FakeLLM(LLMClient):
    """Stands in for Claude: returns canned structured outputs, records prompts."""

    def __init__(self, responses: list[dict[str, Any] | None]):
        super().__init__(enabled=False)
        self.responses = list(responses)
        self.prompts: list[str] = []

    @property
    def available(self) -> bool:
        return True

    async def complete_json(self, *, system: str, prompt: str, schema: dict, max_tokens: int = 4096):
        self.prompts.append(prompt)
        return self.responses.pop(0) if self.responses else None


def test_redaction():
    text = "token eyJhbGciOi.eyJzdWIi.c2ln Bearer abc.def PAN ABCDE1234F acct 123456789012 IFSC HDFC0001234 password=hunter2 sk-ant-api03-xyz"
    cleaned = redact(text)
    for secret in ("eyJhbGciOi", "abc.def", "ABCDE1234F", "123456789012", "HDFC0001234", "hunter2", "sk-ant-api03"):
        assert secret not in cleaned
    assert len(redact("a" * 5000)) <= 2001


def test_production_requires_strong_jwt_secret():
    with pytest.raises(RuntimeError):
        Settings(environment="prod", jwt_secret_key="change_me").validate_for_runtime()
    Settings(environment="prod", jwt_secret_key="x" * 40).validate_for_runtime()
    Settings(environment="dev", jwt_secret_key="change_me").validate_for_runtime()


def test_llm_disabled_without_key():
    assert not LLMClient(api_key="", enabled=True).available
    assert LLMClient(api_key="", enabled=True).provider_name == "rule-based"


async def test_llm_generated_destructive_sql_is_still_blocked(users):
    llm = FakeLLM([{"answerable": True, "sql": "DROP TABLE employees"}])
    result = await run_sql_agent("Which projects are ongoing?", users["admin"], llm)
    assert result.status.value == "BLOCKED"


async def test_llm_generated_sensitive_sql_is_still_blocked(users):
    llm = FakeLLM([{"answerable": True, "sql": "SELECT name, bank_account_number FROM employees"}])
    result = await run_sql_agent("List employee names", users["admin"], llm)
    assert result.status.value == "DENIED"


async def test_llm_sql_is_role_scoped_and_schema_prompt_is_limited(users):
    llm = FakeLLM([{"answerable": True, "sql": "SELECT employee_id, remaining FROM leave_balances"}])
    result = await run_sql_agent("Show leave balances", users["employee"], llm)
    assert {row["employee_id"] for row in result.data["rows"]} == {users["employee"].user_id}
    assert "payroll_records" not in llm.prompts[0]


async def test_llm_unavailable_falls_back_to_rules(users):
    llm = FakeLLM([None])  # e.g. timeout or refusal
    result = await run_sql_agent("Which projects are currently ongoing?", users["employee"], llm)
    assert result.status.value == "ANSWERED"


async def test_llm_policy_answer_uses_cited_sources(users):
    llm = FakeLLM([{"answerable": True, "answer": "You get 10 sick days per year (Leave Policy).", "source_ids": [0]}])
    async with SessionLocal() as db:
        result = await answer_policy_question(db, "How many sick leaves can I take?", users["employee"], llm)
    assert result.answer.startswith("You get 10 sick days")
    assert result.data["sources"][0]["title"] == "Leave Policy"
    assert "<policy_document" in llm.prompts[0]  # context is delimited as untrusted data


async def test_llm_policy_unanswerable_refuses(users):
    llm = FakeLLM([{"answerable": False, "answer": "", "source_ids": []}])
    async with SessionLocal() as db:
        result = await answer_policy_question(db, "What is the leave policy?", users["employee"], llm)
    assert result.status.value == "NO_ANSWER"


async def test_llm_action_plan_still_permission_checked(users):
    llm = FakeLLM([{"tool": "approve_leave_request", "args": {"request_id": 2}}])
    result = await run_action_agent("please approve 2", users["employee"], llm)
    assert result.status.value == "DENIED"


async def test_llm_classification_used_when_available():
    llm = FakeLLM([{"intent": "SQL_QUERY", "confidence": 0.9, "reason": "lookup"}])
    result = await classify("Who works on the copilot?", llm)
    assert result.intent.value == "SQL_QUERY"
    # Raw SQL never reaches the LLM classifier.
    raw = await classify("DROP TABLE employees", FakeLLM([]))
    assert raw.intent.value == "SQL_QUERY"


async def test_weak_retrieval_is_rewritten_into_policy_terms(users):
    # "show up at 9:20" shares no words with the attendance policy; the model rewrites it, then answers.
    llm = FakeLLM(
        [
            {"queries": ["clock-in time late arrival attendance"]},
            {"answerable": True, "answer": "Clocking in after 9:00 AM is marked as late, so 9:20 would be late.", "source_ids": [0]},
        ]
    )
    async with SessionLocal() as db:
        result = await answer_policy_question(db, "Is it ok if I show up at 9:20 in the morning?", users["employee"], llm)
    assert result.status.value == "ANSWERED"
    assert result.data["sources"][0]["title"] == "Attendance Policy"
    assert len(llm.prompts) == 2 and "Attendance Policy" in llm.prompts[1]


async def test_unanswerable_first_pass_retries_with_rewritten_query(users):
    llm = FakeLLM(
        [
            {"answerable": False, "answer": "", "source_ids": []},
            {"queries": ["late arrival clock-in attendance"]},
            {"answerable": True, "answer": "Arrivals after 9:00 AM are marked late.", "source_ids": [0]},
        ]
    )
    async with SessionLocal() as db:
        result = await answer_policy_question(db, "What happens if I am late for the leave policy meeting?", users["employee"], llm)
    assert result.status.value == "ANSWERED"
    assert any(s["title"] == "Attendance Policy" for s in result.data["sources"])


async def test_rewrite_still_refuses_off_topic_questions(users):
    llm = FakeLLM([{"queries": ["capital city of France"]}, {"answerable": False, "answer": "", "source_ids": []}])
    async with SessionLocal() as db:
        result = await answer_policy_question(db, "What is the capital of France?", users["employee"], llm)
    assert result.status.value == "NO_ANSWER"
