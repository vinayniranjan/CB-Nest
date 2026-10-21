"""Local vector store for policy chunks, persisted in the ``ai_policy_chunks`` table.

The policy library is small (tens of documents), so exact cosine search over
all chunks is fast and avoids running a separate vector database.
"""

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_policy_chunk import AIPolicyChunk
from app.services.ai.embeddings import cosine_similarity


@dataclass(frozen=True)
class ChunkRecord:
    policy_id: int
    chunk_index: int
    title: str
    category: str
    filename: str | None
    content: str
    index_key: str
    embedding: list[float]


@dataclass(frozen=True)
class SearchHit:
    policy_id: int
    chunk_index: int
    title: str
    category: str
    filename: str | None
    content: str
    score: float


class PolicyVectorStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def index_keys(self) -> dict[int, str]:
        rows = (await self.db.execute(select(AIPolicyChunk.policy_id, AIPolicyChunk.policy_checksum).distinct())).all()
        return {policy_id: key for policy_id, key in rows}

    async def delete_policies(self, policy_ids: list[int]) -> None:
        if policy_ids:
            await self.db.execute(delete(AIPolicyChunk).where(AIPolicyChunk.policy_id.in_(policy_ids)))

    async def add(self, chunks: list[ChunkRecord]) -> None:
        for chunk in chunks:
            self.db.add(
                AIPolicyChunk(
                    policy_id=chunk.policy_id,
                    chunk_index=chunk.chunk_index,
                    title=chunk.title,
                    category=chunk.category,
                    filename=chunk.filename,
                    content=chunk.content,
                    policy_checksum=chunk.index_key,
                    embedding=chunk.embedding,
                )
            )

    async def search(self, query_embedding: list[float], top_k: int, min_score: float) -> list[SearchHit]:
        rows = (await self.db.execute(select(AIPolicyChunk))).scalars().all()
        scored = [
            SearchHit(
                policy_id=row.policy_id,
                chunk_index=row.chunk_index,
                title=row.title,
                category=row.category,
                filename=row.filename,
                content=row.content,
                score=cosine_similarity(query_embedding, row.embedding),
            )
            for row in rows
        ]
        scored = [hit for hit in scored if hit.score >= min_score]
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:top_k]
