"""Unit tests for all Pydantic data models."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from insightforge.models.chunk import Chunk, ChunkBatch
from insightforge.models.frame import Frame, FrameSet
from insightforge.models.output import NoteSection, FinalOutput
from insightforge.models.scoring import ScoredChunk
from insightforge.models.transcript import TranscriptSegment, TranscriptResult
from insightforge.models.video import VideoJob, VideoMetadata


# ---------------------------------------------------------------------------
# TranscriptSegment
# ---------------------------------------------------------------------------


class TestTranscriptSegment:
    def test_valid_segment(self):
        seg = TranscriptSegment(start=0.0, end=5.0, text="Hello world")
        assert seg.duration == 5.0
        assert seg.timestamp_str == "00:00"

    def test_end_before_start_raises(self):
        with pytest.raises(ValidationError):
            TranscriptSegment(start=10.0, end=5.0, text="Bad segment")

    def test_timestamp_str_hours(self):
        seg = TranscriptSegment(start=3661.0, end=3665.0, text="Deep in the video")
        assert seg.timestamp_str == "1:01:01"


# ---------------------------------------------------------------------------
# TranscriptResult
# ---------------------------------------------------------------------------


class TestTranscriptResult:
    def test_word_count_computed(self, sample_transcript):
        assert sample_transcript.word_count > 0

    def test_full_text_joins_segments(self, sample_segments):
        result = TranscriptResult(segments=sample_segments, source="whisper")
        assert "Hello" in result.full_text
        assert "decorators" in result.full_text

    def test_duration_seconds(self, sample_transcript):
        assert sample_transcript.duration_seconds == 40.0


# ---------------------------------------------------------------------------
# Chunk
# ---------------------------------------------------------------------------


class TestChunk:
    def test_midpoint(self, sample_chunk):
        assert sample_chunk.midpoint == pytest.approx(6.0)

    def test_end_before_start_raises(self):
        with pytest.raises(ValidationError):
            Chunk(chunk_id="c0", text="bad", start=10.0, end=5.0)

    def test_timestamp_str(self, sample_chunk):
        assert sample_chunk.timestamp_str == "00:00"


# ---------------------------------------------------------------------------
# ChunkBatch
# ---------------------------------------------------------------------------


class TestChunkBatch:
    def test_len(self, sample_chunk_batch):
        assert len(sample_chunk_batch) == 2

    def test_total_tokens_computed(self, sample_chunk_batch):
        assert sample_chunk_batch.total_tokens == 30


# ---------------------------------------------------------------------------
# Frame
# ---------------------------------------------------------------------------


class TestFrame:
    def test_markdown_ref(self, sample_frame):
        ref = sample_frame.markdown_ref
        assert ref.startswith("![")
        assert "frame_0000.jpg" in ref

    def test_timestamp_str(self, sample_frame):
        assert sample_frame.timestamp_str == "00:06"


# ---------------------------------------------------------------------------
# FrameSet
# ---------------------------------------------------------------------------


class TestFrameSet:
    def test_get_frame_near_found(self, sample_frame_set, sample_frame):
        result = sample_frame_set.get_frame_near(6.5, tolerance=2.0)
        assert result is not None
        assert result.frame_id == sample_frame.frame_id

    def test_get_frame_near_not_found(self, sample_frame_set):
        result = sample_frame_set.get_frame_near(100.0, tolerance=1.0)
        assert result is None

    def test_len(self, sample_frame_set):
        assert len(sample_frame_set) == 1


# ---------------------------------------------------------------------------
# ScoredChunk
# ---------------------------------------------------------------------------


class TestScoredChunk:
    def test_compute_composite(self, sample_chunk):
        sc = ScoredChunk(chunk=sample_chunk, llm_score=1.0, visual_score=0.0)
        sc.compute_composite(llm_weight=0.7, visual_weight=0.3)
        assert sc.composite_score == pytest.approx(0.7)

    def test_is_important_true(self, sample_scored_chunk):
        assert sample_scored_chunk.is_important is True

    def test_score_out_of_range_raises(self, sample_chunk):
        with pytest.raises(ValidationError):
            ScoredChunk(chunk=sample_chunk, llm_score=1.5)


# ---------------------------------------------------------------------------
# VideoJob
# ---------------------------------------------------------------------------


class TestVideoJob:
    def test_valid_job(self, sample_video_job):
        assert sample_video_job.mode == "local"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValidationError):
            VideoJob(url="https://youtube.com/watch?v=test", mode="invalid")

    def test_invalid_detail_raises(self):
        with pytest.raises(ValidationError):
            VideoJob(url="https://youtube.com/watch?v=test", detail="medium")


# ---------------------------------------------------------------------------
# VideoMetadata
# ---------------------------------------------------------------------------


class TestVideoMetadata:
    def test_duration_human_minutes(self, sample_video_metadata):
        assert sample_video_metadata.duration_human == "10:00"

    def test_duration_human_hours(self):
        meta = VideoMetadata(
            video_id="abc",
            title="Long Video",
            channel="Channel",
            duration_seconds=3661.0,
        )
        assert meta.duration_human == "1:01:01"
