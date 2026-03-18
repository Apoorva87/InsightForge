"""Unit tests for the hosted HTML viewer server helpers."""

from __future__ import annotations

from insightforge.viewer_server import _strip_reasoning


def test_strip_reasoning_removes_think_blocks() -> None:
    text = "<think>hidden analysis</think>\nFinal answer."

    assert _strip_reasoning(text) == "Final answer."


def test_strip_reasoning_removes_reasoning_prefix() -> None:
    text = "Reasoning: this is hidden\n\nDirect answer here."

    assert _strip_reasoning(text) == "Direct answer here."
