"""Unit tests for config loading and env overrides."""

from __future__ import annotations

from pathlib import Path

from insightforge.utils.config import load_config
from insightforge.utils.config import _apply_env_overrides


def test_frame_rerank_env_override_disables_vlm(monkeypatch):
    config = {"frames": {"vlm_rerank_enabled": True}}
    monkeypatch.setenv("INSIGHTFORGE_FRAME_RERANK", "heuristic")
    updated = _apply_env_overrides(config)
    assert updated["frames"]["vlm_rerank_enabled"] is False


def test_frame_rerank_env_override_enables_vlm(monkeypatch):
    config = {"frames": {"vlm_rerank_enabled": False}}
    monkeypatch.setenv("INSIGHTFORGE_FRAME_RERANK", "vlm")
    updated = _apply_env_overrides(config)
    assert updated["frames"]["vlm_rerank_enabled"] is True


def test_educational_preset_prefers_smaller_subsections():
    config = load_config(Path("config/presets/educational.yaml"))
    assert config["llm_processing"]["max_chunk_summaries_per_subsection"] == 2
