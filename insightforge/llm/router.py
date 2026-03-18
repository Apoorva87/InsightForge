"""LLM Router — selects and falls back between providers based on config mode."""

from __future__ import annotations

from typing import Optional

from insightforge.llm.base import LLMProvider, LLMProviderError, LLMRequest, LLMResponse


class LLMRouter:
    """Routes LLM requests to the appropriate provider with automatic fallback.

    Mode "local":  Ollama → LMStudio (OpenAI-compatible)
    Mode "api":    Anthropic only

    Args:
        mode: "local" or "api".
        providers: Ordered list of providers to try. If None, built from config.
    """

    def __init__(self, mode: str = "local", providers: Optional[list[LLMProvider]] = None) -> None:
        if mode not in ("local", "api"):
            raise ValueError(f"mode must be 'local' or 'api', got {mode!r}")
        self.mode = mode
        self._providers: list[LLMProvider] = providers or []

    @classmethod
    def from_config(cls, config: dict) -> "LLMRouter":
        """Build an LLMRouter from the parsed config dict.

        Args:
            config: Full config dict (as loaded by utils.config).

        Returns:
            Configured LLMRouter instance.
        """
        from insightforge.llm.ollama_provider import OllamaProvider
        from insightforge.llm.openai_provider import OpenAIProvider
        from insightforge.llm.anthropic_provider import AnthropicProvider

        mode = config.get("llm", {}).get("mode", "local")
        providers: list[LLMProvider] = []

        if mode == "local":
            ollama_cfg = config.get("llm", {}).get("ollama", {})
            providers.append(
                OllamaProvider(
                    base_url=ollama_cfg.get("base_url", "http://localhost:11434"),
                    model=ollama_cfg.get("model", "qwen2.5:14b"),
                    timeout=ollama_cfg.get("timeout", 120),
                )
            )
            lmstudio_cfg = config.get("llm", {}).get("lmstudio", {})
            if lmstudio_cfg:
                providers.append(
                    OpenAIProvider(
                        api_key="lm-studio",
                        base_url=lmstudio_cfg.get("base_url", "http://localhost:1234/v1"),
                        model=lmstudio_cfg.get("model") or "local-model",
                        provider_name="lmstudio",
                    )
                )
        elif mode == "api":
            import os
            anthropic_cfg = config.get("llm", {}).get("anthropic", {})
            providers.append(
                AnthropicProvider(
                    api_key=os.environ.get("ANTHROPIC_API_KEY"),
                    model=anthropic_cfg.get("model", "claude-haiku-4-5-20251001"),
                    max_tokens=anthropic_cfg.get("max_tokens", 4096),
                )
            )

        return cls(mode=mode, providers=providers)

    def add_provider(self, provider: LLMProvider) -> None:
        """Append a provider to the fallback chain."""
        self._providers.append(provider)

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Try providers in order; return first success; raise if all fail.

        Args:
            request: LLM request to send.

        Returns:
            LLMResponse from the first responding provider.

        Raises:
            LLMProviderError: If all providers fail.
        """
        if not self._providers:
            raise LLMProviderError("router", "No providers configured.")

        last_error: Optional[LLMProviderError] = None
        for provider in self._providers:
            try:
                return provider.complete(request)
            except LLMProviderError as exc:
                last_error = exc
                continue

        raise LLMProviderError(
            "router",
            f"All providers failed. Last error: {last_error}",
            cause=last_error,
        )

    @property
    def providers(self) -> list[LLMProvider]:
        return list(self._providers)
