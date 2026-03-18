"""Abstract LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel


class LLMRequest(BaseModel):
    """Provider-agnostic LLM request."""

    prompt: str
    system: Optional[str] = None
    max_tokens: int = 1024
    temperature: float = 0.3
    stop: list[str] = []
    response_format: Optional[dict[str, Any]] = None
    extra_body: Optional[dict[str, Any]] = None


class LLMResponse(BaseModel):
    """Provider-agnostic LLM response."""

    text: str
    model: str
    provider: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[float] = None


class LLMProvider(ABC):
    """Abstract base class for all LLM providers.

    Implementors must override `complete` and `name`.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name, e.g. 'ollama', 'anthropic'."""
        ...

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request and return the response synchronously.

        Args:
            request: Provider-agnostic request parameters.

        Returns:
            LLMResponse with the generated text.

        Raises:
            LLMProviderError: On transport or API-level errors.
        """
        ...

    def is_available(self) -> bool:
        """Check whether the provider endpoint is reachable.

        Default implementation always returns True; override for health-check logic.
        """
        return True


class LLMProviderError(Exception):
    """Raised when an LLM provider call fails."""

    def __init__(self, provider: str, message: str, cause: Optional[Exception] = None) -> None:
        self.provider = provider
        self.cause = cause
        super().__init__(f"[{provider}] {message}")
