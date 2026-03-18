"""OpenAI-compatible LLM provider.

Supports:
- OpenAI cloud (api_key + default base_url)
- LMStudio local (base_url=http://localhost:1234/v1, api_key="lm-studio")
- Any other OpenAI-compatible endpoint
"""

from __future__ import annotations

import time
from typing import Optional

from insightforge.llm.base import LLMProvider, LLMProviderError, LLMRequest, LLMResponse


class OpenAIProvider(LLMProvider):
    """Calls any OpenAI-compatible /chat/completions endpoint."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o-mini",
        provider_name: str = "openai",
    ) -> None:
        """
        Args:
            api_key: API key. For LMStudio use "lm-studio" or any non-empty string.
            base_url: Override base URL. E.g. "http://localhost:1234/v1" for LMStudio.
            model: Model identifier.
            provider_name: Label used in LLMResponse.provider (e.g. "lmstudio").
        """
        try:
            import openai as _openai
        except ImportError as exc:
            raise ImportError(
                "openai package is required for OpenAIProvider. "
                "Install it with: pip install openai"
            ) from exc

        self._openai = _openai
        kwargs: dict = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = _openai.OpenAI(**kwargs)
        self.model = model
        self._provider_name = provider_name

    @property
    def name(self) -> str:
        return self._provider_name

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Call the OpenAI-compatible chat completions endpoint."""
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.stop:
            kwargs["stop"] = request.stop

        start = time.monotonic()
        try:
            response = self._client.chat.completions.create(**kwargs)
        except self._openai.OpenAIError as exc:
            raise LLMProviderError(self.name, str(exc), cause=exc) from exc

        elapsed_ms = (time.monotonic() - start) * 1000
        choice = response.choices[0]
        text = choice.message.content or ""

        return LLMResponse(
            text=text,
            model=response.model,
            provider=self.name,
            input_tokens=response.usage.prompt_tokens if response.usage else None,
            output_tokens=response.usage.completion_tokens if response.usage else None,
            latency_ms=elapsed_ms,
        )

    def is_available(self) -> bool:
        """Attempt a lightweight models list call to check availability."""
        try:
            self._client.models.list()
            return True
        except Exception:
            return False
