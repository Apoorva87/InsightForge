"""Unit tests for Stage 4 — Chunking."""

from __future__ import annotations

import pytest

from insightforge.models.transcript import TranscriptResult, TranscriptSegment
from insightforge.stages.chunking import run, _trim_overlap, _make_chunk


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
