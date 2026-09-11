"""Provider-neutral OpenAI-compatible structured-output client."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """The configured model endpoint could not produce a valid response."""


SUPPORTED_PROVIDERS = frozenset({"kimi", "deepseek", "glm"})


@dataclass(frozen=True)
class LLMExtractionResult:
    cards: list[dict[str, Any]]
    telemetry: dict[str, int | str | None]


class OpenAICompatibleKnowledgeClient:
    """Works with Kimi, DeepSeek and GLM deployments exposing chat completions."""

    def __init__(
        self, provider: str, base_url: str, api_key: str, model: str, timeout_seconds: float
    ) -> None:
        if provider.lower() not in SUPPORTED_PROVIDERS:
            raise ValueError(f"unsupported knowledge LLM provider: {provider}")
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("knowledge LLM base URL must be absolute HTTP(S)")
        if not api_key:
            raise ValueError("knowledge LLM API key is required")
        self._provider = provider.lower()
        self._base_url = base_url.rstrip("/")
        self._api_key, self._model, self._timeout_seconds = api_key, model, timeout_seconds

    async def extract(self, prompt: str) -> LLMExtractionResult:
        logger.info(
            "knowledge_llm_request_started",
            extra={
                "event": "knowledge.llm.request.started",
                "provider": self._provider,
                "model": self._model,
            },
        )
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "knowledge_llm_request_failed",
                extra={
                    "event": "knowledge.llm.request.failed",
                    "provider": self._provider,
                    "model": self._model,
                },
            )
            raise LLMUnavailable("knowledge model request failed") from exc
        try:
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            cards = parsed["cards"]
            usage = data.get("usage") or {}
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMUnavailable("knowledge model returned invalid structured output") from exc
        if not isinstance(cards, list) or not all(isinstance(card, dict) for card in cards):
            raise LLMUnavailable("knowledge model cards payload is invalid")
        return LLMExtractionResult(
            cards=cards,
            telemetry={
                "provider": self._provider,
                "model": self._model,
                "prompt_tokens": _optional_int(usage.get("prompt_tokens")),
                "completion_tokens": _optional_int(usage.get("completion_tokens")),
            },
        )

    async def extract_cards(self, prompt: str) -> list[dict[str, Any]]:
        """Compatibility helper for callers only interested in candidate cards."""
        return (await self.extract(prompt)).cards


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None
