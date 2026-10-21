"""Embedding generation for policy retrieval.

Default backend: a deterministic, dependency-free *hashed* embedding
(unigrams + bigrams, HR-domain synonym normalisation, light stemming, sublinear
TF, L2-normalised). It is fast, reproducible in tests and needs no model download.

Optional backend: ``AI_EMBEDDING_BACKEND=fastembed`` uses a local ONNX sentence
embedding model (BAAI/bge-small-en-v1.5) when the ``fastembed`` package is installed.
Changing backend re-indexes automatically because the backend name is part of
each chunk's index key.
"""

import hashlib
import math
import re
from collections import Counter
from functools import lru_cache
from typing import Protocol

from app.core.config import settings

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    """a an and are as at be been but by can could do does did for from get got has have how i if in into is it its
    me my of on or our please should so tell that the their them there these this to us was we what when where which
    who whom why will with would you your yours about any all am also than then what's i'm""".split()
)

# Phrase-level normalisation applied before tokenising, so that different ways of
# saying the same HR concept land on the same features.
_PHRASE_SYNONYMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bwork(ing)?[\s-]+from[\s-]+home\b"), " wfh "),
    (re.compile(r"\bremote(ly)?\s+work(ing)?\b"), " wfh "),
    (re.compile(r"\bhalf[\s-]+day\b"), " halfday "),
    (re.compile(r"\b(show(ing|ed)?|turn(ing|ed)?)\s+up\b|\barriv(e|es|ed|ing|al|als)\b|\b(come|coming|came)\s+in(to)?\s*(the\s+)?(office|work)?\b|\breach(ing|ed)?\s+(the\s+)?office\b"), " clockin "),
    (re.compile(r"\bclock(ing|ed)?[\s-]+in\b|\blog(ging|ged)?[\s-]+in\b|\bpunch(ing|ed)?[\s-]+in\b"), " clockin "),
    (re.compile(r"\bclock(ing|ed)?[\s-]+out\b|\blog(ging|ged)?[\s-]+out\b"), " clockout "),
    (re.compile(r"\bmedical\s+leave\b|\bsick\s+days?\b|\bsick\s+leaves\b"), " sick leave "),
    (re.compile(r"\bvacation\b|\bholiday\s+leave\b|\bannual\s+leave\b|\bprivilege\s+leave\b"), " earned leave "),
    (re.compile(r"\bpto\b|\btime\s+off\b|\bday\s+off\b|\bdays\s+off\b"), " leave "),
]
_WORD_SYNONYMS = {
    "tardy": "late",
    "delayed": "late",
    "lateness": "late",
    "leaves": "leave",
    "upload": "upload",
    "uploading": "upload",
    "uploaded": "upload",
    "docs": "document",
    "files": "document",
    "file": "document",
    "entitled": "entitlement",
    "eligible": "entitlement",
    "allowance": "entitlement",
}


def _stem(token: str) -> str:
    token = _WORD_SYNONYMS.get(token, token)
    if token.endswith("ies") and len(token) > 5:
        return token[:-3] + "y"
    for suffix in ("ement", "ment", "ing", "ed", "es", "s", "e"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    normalised = text.lower()
    for pattern, replacement in _PHRASE_SYNONYMS:
        normalised = pattern.sub(replacement, normalised)
    return [_stem(tok) for tok in _TOKEN_PATTERN.findall(normalised) if tok not in STOPWORDS and len(tok) > 1]


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    def __init__(self, dimensions: int = 4096):
        self.dimensions = dimensions
        self.name = f"hashing-v2-{dimensions}"

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        sign = 1.0 if value & 1 else -1.0
        return (value >> 1) % self.dimensions, sign

    def embed_one(self, text: str) -> list[float]:
        tokens = tokenize(text)
        features = Counter(tokens)
        features.update(f"{a}_{b}" for a, b in zip(tokens, tokens[1:]))
        vector = [0.0] * self.dimensions
        for feature, count in features.items():
            index, sign = self._bucket(feature)
            weight = 1.0 + math.log(count)
            # Bigrams carry more specific meaning than single words.
            vector[index] += sign * weight * (1.5 if "_" in feature else 1.0)
        norm = math.sqrt(sum(v * v for v in vector))
        # Rounded: keeps the JSON stored per chunk small without affecting ranking.
        return [round(v / norm, 6) for v in vector] if norm else vector

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(text) for text in texts]


class FastEmbedEmbedder:  # pragma: no cover - optional dependency
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)
        self.name = f"fastembed-{model_name.split('/')[-1]}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, vector)) for vector in self._model.embed(texts)]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    if settings.ai_embedding_backend == "fastembed":  # pragma: no cover - optional dependency
        return FastEmbedEmbedder()
    return HashingEmbedder()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)
