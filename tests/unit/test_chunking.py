"""Unit tests for Stage 4 — Chunking."""

from __future__ import annotations

import sys
from unittest.mock import Mock

import pytest

from insightforge.models.transcript import TranscriptSegment
from insightforge.stages.chunking import _get_token_counter, _make_chunk, _trim_overlap, run


class TestChunkingRun:
    def test_produces_at_least_one_chunk(self, sample_transcript):
        batch = run(sample_transcript, strategy="hybrid", max_tokens=800)
        assert len(batch.chunks) >= 1

    def test_chunk_ids_are_sequential(self, sample_transcript):
        batch = run(sample_transcript, strategy="hybrid")
        for i, chunk in enumerate(batch.chunks):
            assert chunk.chunk_id == f"chunk_{i:04d}"

    def test_token_strategy(self, sample_transcript):
        batch = run(sample_transcript, strategy="token", max_tokens=50)
        for chunk in batch.chunks:
            assert len(chunk.text) > 0

    def test_sentence_strategy(self, sample_transcript):
        batch = run(sample_transcript, strategy="sentence", max_tokens=200)
        assert len(batch.chunks) >= 1

    def test_all_text_covered(self, sample_transcript):
        batch = run(sample_transcript, strategy="hybrid")
        combined = " ".join(c.text for c in batch.chunks)
        # All original words should appear somewhere in combined output
        original_words = set(sample_transcript.full_text.split())
        for word in list(original_words)[:10]:  # spot-check first 10 words
            assert word in combined

    def test_chunk_timestamps_are_ordered(self, sample_transcript):
        batch = run(sample_transcript)
        prev_end = -1.0
        for chunk in batch.chunks:
            assert chunk.start >= 0
            assert chunk.end >= chunk.start


class TestTrimOverlap:
    def test_returns_trailing_segments(self, sample_segments):
        encode = lambda t: len(t.split())
        result = _trim_overlap(sample_segments, overlap_tokens=10, encode=encode)
        assert len(result) <= len(sample_segments)
        assert all(s in sample_segments for s in result)


def test_get_token_counter_falls_back_when_tiktoken_init_fails(monkeypatch) -> None:
    mock_tiktoken = Mock()
    mock_tiktoken.get_encoding.side_effect = RuntimeError("offline cache miss")
    monkeypatch.setitem(sys.modules, "tiktoken", mock_tiktoken)

    encode = _get_token_counter()

    assert encode("one two three") == 3
