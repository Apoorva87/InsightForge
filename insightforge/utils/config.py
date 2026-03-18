"""Config loading — merges default.yaml with optional user config and env overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml


_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "default.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge `override` into `base`, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(user_config_path: Optional[Path] = None) -> dict[str, Any]:
    """Load and merge configuration.

    Resolution order (later overrides earlier):
    1. config/default.yaml (bundled)
    2. user_config_path (if provided)
    3. Environment variable overrides

    Args:
        user_config_path: Optional path to a user-provided YAML config file.

    Returns:
        Merged config dict.
    """
    with _DEFAULT_CONFIG_PATH.open() as f:
        config = yaml.safe_load(f) or {}

    if user_config_path is not None:
        with Path(user_config_path).open() as f:
            user_cfg = yaml.safe_load(f) or {}
        config = _deep_merge(config, user_cfg)

    config = _apply_env_overrides(config)
    return config


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """Apply environment variable overrides to the config dict."""
    # LLM mode
    if mode := os.environ.get("INSIGHTFORGE_LLM_MODE"):
        config.setdefault("llm", {})["mode"] = mode

    # Ollama URL
    if url := os.environ.get("OLLAMA_BASE_URL"):
        config.setdefault("llm", {}).setdefault("ollama", {})["base_url"] = url

    # LMStudio URL
    if url := os.environ.get("LMSTUDIO_BASE_URL"):
        config.setdefault("llm", {}).setdefault("lmstudio", {})["base_url"] = url

    # Frame reranking strategy
    if rerank := os.environ.get("INSIGHTFORGE_FRAME_RERANK"):
        rerank = rerank.lower().strip()
        frames_cfg = config.setdefault("frames", {})
        if rerank in {"heuristic", "off", "disabled"}:
            frames_cfg["vlm_rerank_enabled"] = False
        elif rerank in {"vlm", "vision", "enabled"}:
            frames_cfg["vlm_rerank_enabled"] = True

    # Output dir
    if out := os.environ.get("INSIGHTFORGE_OUTPUT_DIR"):
        config.setdefault("output", {})["base_dir"] = out

    # Log level
    if level := os.environ.get("INSIGHTFORGE_LOG_LEVEL"):
        config.setdefault("logging", {})["level"] = level

    return config


def get_nested(config: dict, *keys: str, default: Any = None) -> Any:
    """Safely access a nested config value.

    Example:
        get_nested(config, "llm", "ollama", "model", default="llama3.2")
    """
    node = config
    for key in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(key, default)
        if node is default:
            return default
    return node
