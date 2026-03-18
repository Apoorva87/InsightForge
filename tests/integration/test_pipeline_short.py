"""Integration test — smoke test the full pipeline with mocked external calls.

This test validates the complete data flow without downloading real videos
or making real LLM API calls.

Run with: pytest tests/integration/test_pipeline_short.py -v
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from insightforge.models.chunk import Chunk, ChunkBatch
from insightforge.models.frame import FrameSet
from insightforge.models.output import FinalOutput
from insightforge.models.transcript import TranscriptResult, TranscriptSegment
from insightforge.models.video import VideoJob, VideoMetadata
from tests.conftest import MockLLMProvider


@pytest.fixture
def mock_video_path(tmp_path) -> Path:
    p = tmp_path / "work" / "dQw4w9WgXcQ.mp4"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"fake_video_data")
    return p


@pytest.fixture
def mock_metadata(tmp_path) -> VideoMetadata:
    return VideoMetadata(
        video_id="dQw4w9WgXcQ",
        title="Test Video for Integration",
        channel="Test Channel",
        duration_seconds=120.0,
        work_dir=tmp_path / "work",
    )


@pytest.fixture
def mock_transcript() -> TranscriptResult:
    segments = [
        TranscriptSegment(start=0.0, end=10.0, text="Welcome to this test video about Python."),
        TranscriptSegment(start=10.5, end=20.0, text="We will cover decorators and context managers."),
        TranscriptSegment(start=20.5, end=30.0, text="Let us start with a simple decorator example."),
    ]
    return TranscriptResult(segments=segments, source="whisper", language="en")


@pytest.mark.integration
def test_pipeline_stages_3_through_9(
    tmp_path, mock_video_path, mock_metadata, mock_transcript
):
    """Smoke test: run stages 3–9 with real stage code but mocked I/O boundaries."""
    import json

    from insightforge.stages import alignment, chunking, formatter, importance
    from insightforge.stages import llm_processing
    from insightforge.storage import writer

    # Stage 3 — Alignment
    aligned = alignment.run(mock_transcript)
    assert aligned.is_aligned

    # Stage 4 — Chunking
    batch = chunking.run(aligned, strategy="hybrid", max_tokens=200)
    assert len(batch.chunks) >= 1

    # Stage 6 — Importance (no frames, mock LLM)
    mock_llm = MockLLMProvider('{"score": 0.75}')
    scored = importance.run(batch, llm=mock_llm, threshold=0.4)
    assert all(isinstance(s.composite_score, float) for s in scored)

    filtered = importance.filter_by_detail(scored, detail="high", threshold=0.4)
    assert len(filtered) >= 1

    # Stage 7 — LLM Processing
    note_llm = MockLLMProvider(json.dumps({
        "heading": "Python Decorators Overview",
        "summary": "This section covers the basics of Python decorators.",
        "key_points": ["Decorators add behaviour", "Use @ syntax"],
    }))
    sections = llm_processing.run(filtered, llm=note_llm)
    assert len(sections) == len(filtered)

    # Stage 8 — Formatter
    output = formatter.run(sections=sections, metadata=mock_metadata)
    assert "# Test Video for Integration" in output.markdown_content
    assert output.section_count == len(sections)

    # Stage 9 — Storage
    result = writer.write(
        output=output,
        metadata=mock_metadata,
        base_dir=tmp_path / "output",
        cleanup_work_dir=False,
    )
    assert result.notes_path.exists()
    assert result.metadata_path.exists()
    meta = json.loads(result.metadata_path.read_text())
    assert meta["video_id"] == "dQw4w9WgXcQ"
