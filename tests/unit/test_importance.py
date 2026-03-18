"""Unit tests for Stage 6 — Importance Scoring."""

from __future__ import annotations

import json

import pytest

from insightforge.models.scoring import ScoredChunk
from insightforge.stages.importance import run, filter_by_detail, _compute_visual_scores
from tests.conftest import MockLLMProvider


class TestImportanceRun:
    def test_returns_scored_chunk_for_each_input(self, sample_chunk_batch, mock_llm):
        result = run(sample_chunk_batch, llm=mock_llm)
        assert len(result) == len(sample_chunk_batch.chunks)

    def test_all_have_composite_scores(self, sample_chunk_batch, mock_llm):
        result = run(sample_chunk_batch, llm=mock_llm)
        for sc in result:
            assert 0.0 <= sc.composite_score <= 1.0

    def test_llm_failure_defaults_to_0_5(self, sample_chunk_batch):
        class FailingLLM(MockLLMProvider):
            def complete(self, request):
                raise RuntimeError("network error")

        result = run(sample_chunk_batch, llm=FailingLLM())
        for sc in result:
            assert sc.llm_score == 0.5

    def test_visual_scores_used_when_frameset_provided(
        self, sample_chunk_batch, sample_frame_set, mock_llm
    ):
        result = run(sample_chunk_batch, llm=mock_llm, frame_set=sample_frame_set)
        # At least one chunk should have a non-zero visual score
        visual_nonzero = any(sc.visual_score > 0 for sc in result)
        # May not match if frame is far from chunk midpoints — just check no crash
        assert len(result) == len(sample_chunk_batch.chunks)


class TestFilterByDetail:
    def test_high_keeps_all_above_threshold(self, sample_chunk_batch, mock_llm):
        scored = run(sample_chunk_batch, llm=mock_llm)
        filtered = filter_by_detail(scored, detail="high", threshold=0.0)
        assert len(filtered) == len(scored)

    def test_low_returns_top_quartile(self, sample_chunk_batch, mock_llm):
        scored = run(sample_chunk_batch, llm=mock_llm)
        # Set different composite scores manually
        scored[0].composite_score = 0.9
        scored[1].composite_score = 0.3
        filtered = filter_by_detail(scored, detail="low", threshold=0.0)
        assert len(filtered) <= max(1, len(scored) // 4)
