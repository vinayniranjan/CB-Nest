import time
from collections import defaultdict, deque

from app.core.config import settings


class SlidingWindowRateLimiter:
    """Per-user request limit for AI endpoints (LLM calls are the expensive path).

    In-process only: with several API workers each enforces its own window. Use a
    shared store such as Redis when scaling out horizontally.
    """

    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, user_id: int) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic()
        hits = self._hits[user_id]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


ai_rate_limiter = SlidingWindowRateLimiter(settings.ai_rate_limit_per_minute)
