"""Thin Claude client used by every agent.

All calls request JSON that matches a schema (structured outputs). Any failure
(no key, network, refusal, invalid JSON) returns ``None`` and the caller falls
back to its deterministic rule-based path, so the copilot degrades gracefully
instead of failing the request.
"""

import json
import logging
from typing import Any

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, enabled: bool | None = None):
        key = api_key if api_key is not None else settings.anthropic_api_key
        is_enabled = settings.ai_llm_enabled if enabled is None else enabled
        self.model = model or settings.ai_model
        self._client: anthropic.AsyncAnthropic | None = None
        if is_enabled and key:
            self._client = anthropic.AsyncAnthropic(
                api_key=key, timeout=settings.ai_llm_timeout_seconds, max_retries=1
            )

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def provider_name(self) -> str:
        return f"anthropic:{self.model}" if self.available else "rule-based"

    async def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        max_tokens: int = 4096,
    ) -> dict[str, Any] | None:
        if self._client is None:
            return None
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {
                "effort": settings.ai_effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        }
        try:
            if settings.ai_refusal_fallback:
                response = await self._client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **request
                )
            else:
                response = await self._client.messages.create(**request)
        except anthropic.RateLimitError:
            logger.warning("ai.llm.rate_limited")
            return None
        except anthropic.APIStatusError as exc:
            logger.warning("ai.llm.api_error status=%s", exc.status_code)
            return None
        except anthropic.APIConnectionError:
            logger.warning("ai.llm.connection_error")
            return None

        if response.stop_reason in {"refusal", "max_tokens"}:
            logger.warning("ai.llm.incomplete stop_reason=%s", response.stop_reason)
            return None
        text = next((block.text for block in response.content if block.type == "text"), None)
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("ai.llm.invalid_json")
            return None
        return data if isinstance(data, dict) else None


_default_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client


def set_llm(client: LLMClient | None) -> None:
    """Override the shared client (used by tests)."""
    global _default_client
    _default_client = client
