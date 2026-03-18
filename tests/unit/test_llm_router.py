"""Unit tests for LLMRouter."""

from __future__ import annotations

import pytest

from insightforge.llm.base import LLMProviderError, LLMRequest, LLMResponse
from insightforge.llm.router import LLMRouter
from insightforge.models.video import VideoJob
from insightforge.pipeline import _apply_job_overrides
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

    def test_from_config_local_ollama_first_lmstudio_second(self, sample_config):
        """Ollama must be the primary provider; LMStudio is fallback."""
        sample_config["llm"]["lmstudio"] = {
            "base_url": "http://localhost:1234/v1",
            "model": "local-model",
        }
        router = LLMRouter.from_config(sample_config)
        names = [p.name for p in router.providers]
        assert names == ["ollama", "lmstudio"]

    def test_from_config_api_mode(self, sample_config):
        import os
        sample_config["llm"]["mode"] = "api"
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("ANTHROPIC_API_KEY", "sk-test-key")
            router = LLMRouter.from_config(sample_config)
        assert router.mode == "api"


class TestJobOverrides:
    def test_cli_mode_override_wins_over_config(self, sample_config):
        job = VideoJob(url="https://youtube.com/watch?v=test", mode="api")
        merged = _apply_job_overrides(sample_config, job)
        assert merged["llm"]["mode"] == "api"

    def test_cli_model_override_updates_local_providers(self, sample_config):
        sample_config["llm"]["lmstudio"] = {"base_url": "http://localhost:1234/v1", "model": "old"}
        job = VideoJob(
            url="https://youtube.com/watch?v=test",
            mode="local",
            model_override="new-model",
        )
        merged = _apply_job_overrides(sample_config, job)
        assert merged["llm"]["ollama"]["model"] == "new-model"
        assert merged["llm"]["lmstudio"]["model"] == "new-model"

    def test_cli_model_override_updates_api_provider(self, sample_config):
        sample_config["llm"]["anthropic"] = {"model": "old-api-model"}
        job = VideoJob(
            url="https://youtube.com/watch?v=test",
            mode="api",
            model_override="new-api-model",
        )
        merged = _apply_job_overrides(sample_config, job)
        assert merged["llm"]["anthropic"]["model"] == "new-api-model"
