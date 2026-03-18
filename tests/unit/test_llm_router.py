"""Unit tests for LLMRouter."""

from __future__ import annotations

import pytest

from insightforge.llm.base import LLMProviderError, LLMRequest, LLMResponse
from insightforge.llm.router import LLMRouter
from tests.conftest import MockLLMProvider


class TestLLMRouter:
    def test_routes_to_first_provider(self):
        router = LLMRouter(mode="local", providers=[MockLLMProvider('{"score": 0.9}')])
        response = router.complete(LLMRequest(prompt="test"))
        assert response.provider == "mock"

    def test_falls_back_to_second_provider(self):
        class FailFirst(MockLLMProvider):
            def complete(self, request):
                raise LLMProviderError("fail", "always fails")

        fallback = MockLLMProvider('{"score": 0.5}')
        router = LLMRouter(mode="local", providers=[FailFirst(), fallback])
        response = router.complete(LLMRequest(prompt="test"))
        assert response.provider == "mock"

    def test_raises_when_all_providers_fail(self):
        class AlwaysFail(MockLLMProvider):
            def complete(self, request):
                raise LLMProviderError("fail", "always fails")

        router = LLMRouter(mode="local", providers=[AlwaysFail(), AlwaysFail()])
        with pytest.raises(LLMProviderError):
            router.complete(LLMRequest(prompt="test"))

    def test_raises_with_no_providers(self):
        router = LLMRouter(mode="local", providers=[])
        with pytest.raises(LLMProviderError):
            router.complete(LLMRequest(prompt="test"))

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            LLMRouter(mode="cloud")

    def test_add_provider(self):
        router = LLMRouter(mode="local", providers=[])
        router.add_provider(MockLLMProvider())
        assert len(router.providers) == 1

    def test_from_config_local_mode(self, sample_config):
        router = LLMRouter.from_config(sample_config)
        assert router.mode == "local"
        assert len(router.providers) >= 1

    def test_from_config_api_mode(self, sample_config):
        import os
        sample_config["llm"]["mode"] = "api"
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("ANTHROPIC_API_KEY", "sk-test-key")
            router = LLMRouter.from_config(sample_config)
        assert router.mode == "api"
