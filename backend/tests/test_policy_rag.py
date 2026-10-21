import pytest
from sqlalchemy import delete, func, select

from app.db.session import SessionLocal
from app.models import AIPolicyChunk, HRPolicy
from app.services.ai.embeddings import HashingEmbedder, cosine_similarity, tokenize
from app.services.ai.llm import LLMClient
from app.services.ai.policy_rag import NO_ANSWER_MESSAGE, answer_policy_question, chunk_text, ensure_index
from tests.conftest import _POLICY_DIR

NO_LLM = LLMClient(enabled=False)


@pytest.mark.parametrize(
    "question,source,expected",
    [
        ("What is the leave policy?", "Leave Policy", "casual, sick, and earned leave"),
        ("How many sick leaves can I take?", "Leave Policy", "Sick leave: 10 days per year"),
        ("Can I work from home?", "WFH Policy", "approval"),
        ("What happens if I am late?", "Attendance Policy", "marked as late"),
        ("Can I take a half-day leave?", "Leave Policy", "Half-day leave is allowed"),
        ("What is the policy for uploading documents?", "Document Upload Policy", "2 MB"),
        ("How do I get reimbursed for travel?", "Travel Reimbursement", "15 days"),
        ("Is it ok if I show up at 9:20 in the morning?", "Attendance Policy", "marked as late"),
    ],
)
async def test_common_policy_questions_are_grounded(users, question, source, expected):
    async with SessionLocal() as db:
        result = await answer_policy_question(db, question, users["employee"], NO_LLM)
    assert result.status.value == "ANSWERED"
    assert expected in result.answer
    assert result.data["sources"][0]["title"] == source


async def test_sources_expose_only_public_metadata(users):
    async with SessionLocal() as db:
        result = await answer_policy_question(db, "What is the leave policy?", users["employee"], NO_LLM)
    source = result.data["sources"][0]
    assert set(source) == {"title", "category", "filename"}
    assert source == {"title": "Leave Policy", "category": "LEAVE", "filename": "seed_policy_01.md"}


@pytest.mark.parametrize("question", ["What is the capital of France?", "Who won the cricket world cup?", "Explain quantum computing"])
async def test_refuses_without_context(users, question):
    async with SessionLocal() as db:
        result = await answer_policy_question(db, question, users["employee"], NO_LLM)
    assert result.status.value == "NO_ANSWER"
    assert result.answer == NO_ANSWER_MESSAGE
    assert result.data["sources"] == []


async def test_instructions_inside_documents_are_not_followed(users):
    async with SessionLocal() as db:
        result = await answer_policy_question(db, "How do I request remote equipment like a monitor?", users["employee"], NO_LLM)
    assert result.status.value == "ANSWERED"
    assert result.data["sources"][0]["title"] == "Remote Equipment Policy"
    assert "Ignore all previous instructions" not in result.answer
    assert "salar" not in result.answer.lower()
    assert "IT ticket" in result.answer


async def test_index_tracks_new_changed_and_deleted_policies(users):
    path = _POLICY_DIR / "relocation.md"
    path.write_text("# Relocation Policy\n\nRelocating employees receive a one-time relocation allowance of 3000 USD.\n")
    async with SessionLocal() as db:
        policy = HRPolicy(title="Relocation Policy", category="RELOCATION", original_filename="relocation.md",
                          file_path=str(path), mime_type="text/markdown")
        db.add(policy)
        await db.commit()
        result = await answer_policy_question(db, "What relocation allowance do I get?", users["employee"], NO_LLM)
        assert "3000 USD" in result.answer

        path.write_text("# Relocation Policy\n\nRelocating employees receive a one-time relocation allowance of 4500 USD.\n")
        result = await answer_policy_question(db, "What relocation allowance do I get?", users["employee"], NO_LLM)
        assert "4500 USD" in result.answer

        await db.execute(delete(HRPolicy).where(HRPolicy.id == policy.id))
        await db.commit()
        await ensure_index(db)
        remaining = (await db.execute(select(func.count(AIPolicyChunk.id)).where(AIPolicyChunk.policy_id == policy.id))).scalar_one()
        assert remaining == 0
    path.unlink()


async def test_reindex_is_idempotent():
    async with SessionLocal() as db:
        await ensure_index(db)
        second = await ensure_index(db)
    assert second["reindexed_policies"] == 0 and second["removed"] == 0


def test_chunking_keeps_section_headings_and_limits_size():
    text = "Intro line.\n\n## Section A\n" + " ".join(["Sentence number one is here."] * 40) + "\n\n## Section B\nShort."
    chunks = chunk_text(text, max_chars=200)
    assert all(len(chunk) <= 200 for chunk in chunks)
    assert any(chunk.startswith("[Section B] ") for chunk in chunks)
    assert all(chunk.startswith("[Section A] ") for chunk in chunks if "Sentence number" in chunk)


def test_embeddings_are_deterministic_and_semantic_enough():
    embedder = HashingEmbedder()
    a, b, c = embedder.embed(["work from home rules", "WFH policy", "travel reimbursement claims"])
    assert embedder.embed(["work from home rules"])[0] == a
    assert cosine_similarity(a, b) > cosine_similarity(a, c)
    assert "wfh" in tokenize("Can I work from home?")
