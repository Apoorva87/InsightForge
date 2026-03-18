"""Anthropic LLM provider — uses the official anthropic SDK."""

from __future__ import annotations

import time
from typing import Optional

from insightforge.llm.base import LLMProvider, LLMProviderError, LLMRequest, LLMResponse


class AnthropicProvider(LLMProvider):
    """Calls the Anthropic Messages API via the `anthropic` SDK."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 4096,
    ) -> None:
        """
        Args:
            api_key: Anthropic API key. If None, reads from ANTHROPIC_API_KEY env var.
            model: Model identifier.
            max_tokens: Default max output tokens (overridable per request).
        """
        try:
            import anthropic as _anthropic
        except ImportError as exc:
            raise ImportError(
                "anthropic package is required for AnthropicProvider. "
                "Install it with: pip install anthropic"
            ) from exc

        self._anthropic = _anthropic
        self._client = _anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.default_max_tokens = max_tokens

    @property
    def name(self) -> str:
        return "anthropic"

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Call Anthropic Messages API."""
        messages = [{"role": "user", "content": request.prompt}]
        kwargs = {
            "model": self.model,
            "max_tokens": request.max_tokens or self.default_max_tokens,
            "messages": messages,
        }
        if request.system:
            kwargs["system"] = request.system
        if request.stop:
            kwargs["stop_sequences"] = request.stop

        start = time.monotonic()
        try:
            response = self._client.messages.create(**kwargs)
        except self._anthropic.APIError as exc:
            raise LLMProviderError(self.name, str(exc), cause=exc) from exc

        elapsed_ms = (time.monotonic() - start) * 1000
        text = response.content[0].text if response.content else ""

        return LLMResponse(
            text=text,
            model=response.model,
            provider=self.name,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=elapsed_ms,
        )

    def is_available(self) -> bool:
        """Return True if ANTHROPIC_API_KEY is set and client is initialised."""
        import os
        return bool(os.environ.get("ANTHROPIC_API_KEY") or self._client.api_key)
