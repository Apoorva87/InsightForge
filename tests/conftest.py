"""Shared pytest fixtures for InsightForge tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest

from insightforge.llm.base import LLMProvider, LLMRequest, LLMResponse
from insightforge.models.chunk import Chunk, ChunkBatch
from insightforge.models.frame import Frame, FrameSet
from insightforge.models.output import NoteSection, FinalOutput
from insightforge.models.scoring import ScoredChunk
from insightforge.models.transcript import TranscriptResult, TranscriptSegment
from insightforge.models.video import VideoJob, VideoMetadata


# ---------------------------------------------------------------------------
# Model fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(start=0.0, end=5.0, text="Hello and welcome to this tutorial."),
        TranscriptSegment(start=5.5, end=12.0, text="Today we are going to learn about Python decorators."),
        TranscriptSegment(start=12.5, end=20.0, text="Decorators are a powerful feature in Python."),
        TranscriptSegment(start=20.5, end=30.0, text="Let us start with a simple example of a decorator."),
        TranscriptSegment(start=30.5, end=40.0, text="Here we define a wrapper function that adds behaviour."),
    ]


@pytest.fixture
def sample_transcript(sample_segments) -> TranscriptResult:
    return TranscriptResult(segments=sample_segments, source="whisper", language="en")


@pytest.fixture
def sample_chunk() -> Chunk:
    return Chunk(
        chunk_id="chunk_0000",
        text="Hello and welcome to this tutorial. Today we are going to learn about Python decorators.",
        start=0.0,
        end=12.0,
        token_count=17,
    )


@pytest.fixture
def sample_chunk_batch(sample_chunk) -> ChunkBatch:
    chunk2 = Chunk(
        chunk_id="chunk_0001",
        text="Decorators are a powerful feature. Let us start with a simple example.",
        start=12.5,
        end=40.0,
        token_count=13,
    )
    return ChunkBatch(chunks=[sample_chunk, chunk2], strategy="hybrid")


@pytest.fixture
def sample_frame(tmp_path) -> Frame:
    frame_path = tmp_path / "frame_0000.jpg"
    frame_path.write_bytes(b"fake_jpeg")
    return Frame(
        frame_id="frame_0000",
        timestamp=6.0,
        path=frame_path,
        scene_diff_score=0.6,
    )


@pytest.fixture
def sample_frame_set(sample_frame) -> FrameSet:
    return FrameSet(frames=[sample_frame], extraction_mode="scene_change")


@pytest.fixture
def sample_scored_chunk(sample_chunk) -> ScoredChunk:
    sc = ScoredChunk(chunk=sample_chunk, llm_score=0.8, visual_score=0.6)
    sc.compute_composite()
    return sc


@pytest.fixture
def sample_note_section() -> NoteSection:
    return NoteSection(
        section_id="section_0000",
        chunk_id="chunk_0000",
        timestamp_start=0.0,
        timestamp_end=12.0,
        heading="Introduction to Python Decorators",
        summary="This section introduces Python decorators as a powerful language feature.",
        key_points=["Decorators wrap functions", "They add behaviour without modifying source"],
    )


@pytest.fixture
def sample_video_metadata(tmp_path) -> VideoMetadata:
    return VideoMetadata(
        video_id="dQw4w9WgXcQ",
        title="Introduction to Python Decorators",
        channel="Tech Tutorials",
        duration_seconds=600.0,
        upload_date="20240101",
        work_dir=tmp_path / "work",
    )


@pytest.fixture
def sample_video_job() -> VideoJob:
    return VideoJob(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        mode="local",
        detail="high",
    )


# ---------------------------------------------------------------------------
# LLM mock fixture
# ---------------------------------------------------------------------------


class MockLLMProvider(LLMProvider):
    """Deterministic mock LLM provider for unit tests."""

    def __init__(self, response_text: str = '{"score": 0.8}') -> None:
        self._response_text = response_text

    @property
    def name(self) -> str:
        return "mock"

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            text=self._response_text,
            model="mock-model",
            provider="mock",
            input_tokens=10,
            output_tokens=5,
            latency_ms=1.0,
        )


@pytest.fixture
def mock_llm() -> MockLLMProvider:
    return MockLLMProvider()


@pytest.fixture
def mock_llm_note() -> MockLLMProvider:
    """Mock LLM that returns a valid NoteSection JSON."""
    response = json.dumps({
        "heading": "Introduction to Decorators",
        "summary": "This chunk covers the basics of Python decorators.",
        "key_points": ["Decorators modify function behaviour", "They use the @ syntax"],
    })
    return MockLLMProvider(response_text=response)


# ---------------------------------------------------------------------------
# Config fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_config() -> dict:
    """Minimal valid config dict for tests."""
    return {
        "llm": {
            "mode": "local",
            "ollama": {"base_url": "http://localhost:11434", "model": "llama3.2", "timeout": 120},
        },
        "transcript": {"prefer_manual": False, "whisper_model": "base", "language": None},
        "chunking": {"strategy": "hybrid", "max_tokens": 800, "min_tokens": 100, "overlap_tokens": 50},
        "frames": {"enabled": False},
        "importance": {"threshold": 0.4, "llm_weight": 0.7, "visual_weight": 0.3, "batch_size": 5},
        "output": {"base_dir": "./output", "embed_frames_inline": True, "include_timestamp_index": True},
        "logging": {"level": "WARNING", "format": "text"},
        "storage": {"cleanup_work_dir": False},
    }
