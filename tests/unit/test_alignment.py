"""Unit tests for Stage 3 — Alignment."""

from __future__ import annotations

import pytest

from insightforge.models.transcript import TranscriptResult, TranscriptSegment
from insightforge.stages.alignment import (
    _fill_gaps,
    _normalise_whitespace,
    _strip_noise_segments,
    run,
)


class TestStripNoiseSegments:
    def test_removes_music_label(self):
        segs = [
            TranscriptSegment(start=0.0, end=1.0, text="[Music]"),
            TranscriptSegment(start=1.0, end=5.0, text="Hello world"),
        ]
        result = _strip_noise_segments(segs)
        assert len(result) == 1
        assert result[0].text == "Hello world"

    def test_removes_applause(self):
        segs = [TranscriptSegment(start=0.0, end=1.0, text="[Applause]")]
        assert _strip_noise_segments(segs) == []

    def test_keeps_normal_text(self):
        segs = [TranscriptSegment(start=0.0, end=5.0, text="Normal speech here.")]
        assert len(_strip_noise_segments(segs)) == 1


class TestNormaliseWhitespace:
    def test_collapses_whitespace(self):
        segs = [TranscriptSegment(start=0.0, end=5.0, text="  hello   world  ")]
        result = _normalise_whitespace(segs)
        assert result[0].text == "hello world"

    def test_removes_empty_segments(self):
        segs = [
            TranscriptSegment(start=0.0, end=1.0, text="   "),
            TranscriptSegment(start=1.0, end=5.0, text="Valid"),
        ]
        result = _normalise_whitespace(segs)
        assert len(result) == 1


class TestFillGaps:
    def test_fills_small_gap(self):
        segs = [
            TranscriptSegment(start=0.0, end=5.0, text="First"),
            TranscriptSegment(start=6.0, end=10.0, text="Second"),
        ]
        result = _fill_gaps(segs, max_gap=2.0)
        assert result[0].end == 6.0  # extended to next segment start

    def test_does_not_fill_large_gap(self):
        segs = [
            TranscriptSegment(start=0.0, end=5.0, text="First"),
            TranscriptSegment(start=20.0, end=25.0, text="Second"),
        ]
        result = _fill_gaps(segs, max_gap=2.0)
        assert result[0].end == 5.0  # unchanged

    def test_sorts_out_of_order_segments_before_gap_fill(self):
        segs = [
            TranscriptSegment(start=6.0, end=10.0, text="Second"),
            TranscriptSegment(start=0.0, end=5.0, text="First"),
        ]
        result = _fill_gaps(segs, max_gap=2.0)
        assert [segment.text for segment in result] == ["First", "Second"]
        assert result[0].end == 6.0


class TestAlignmentRun:
    def test_is_aligned_flag_set(self, sample_transcript):
        result = run(sample_transcript)
        assert result.is_aligned is True

    def test_output_has_segments(self, sample_transcript):
        result = run(sample_transcript)
        assert len(result.segments) > 0
