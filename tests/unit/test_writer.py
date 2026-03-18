"""Unit tests for Stage 9 — Storage Writer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from insightforge.storage.writer import write
from insightforge.models.output import FinalOutput


class TestStorageWriter:
    def test_writes_notes_md(self, tmp_path, sample_note_section, sample_video_metadata):
        output = FinalOutput(
            video_id=sample_video_metadata.video_id,
            title=sample_video_metadata.title,
            channel=sample_video_metadata.channel,
            duration_seconds=sample_video_metadata.duration_seconds,
            sections=[sample_note_section],
            markdown_content="# Test Notes\n\nSome content here.\n",
        )
        result = write(
            output=output,
            metadata=sample_video_metadata,
            base_dir=tmp_path / "output",
            cleanup_work_dir=False,
        )
        assert result.notes_path is not None
        assert result.notes_path.exists()
        content = result.notes_path.read_text()
        assert "Test Notes" in content

    def test_writes_metadata_json(self, tmp_path, sample_note_section, sample_video_metadata):
        output = FinalOutput(
            video_id=sample_video_metadata.video_id,
            title=sample_video_metadata.title,
            channel=sample_video_metadata.channel,
            duration_seconds=sample_video_metadata.duration_seconds,
            sections=[sample_note_section],
            markdown_content="# Notes\n",
        )
        result = write(
            output=output,
            metadata=sample_video_metadata,
            base_dir=tmp_path / "output",
            cleanup_work_dir=False,
        )
        assert result.metadata_path is not None
        assert result.metadata_path.exists()
        meta = json.loads(result.metadata_path.read_text())
        assert meta["video_id"] == sample_video_metadata.video_id

    def test_creates_frames_dir(self, tmp_path, sample_note_section, sample_video_metadata):
        output = FinalOutput(
            video_id=sample_video_metadata.video_id,
            title=sample_video_metadata.title,
            channel=sample_video_metadata.channel,
            duration_seconds=sample_video_metadata.duration_seconds,
            sections=[sample_note_section],
            markdown_content="# Notes\n",
        )
        result = write(
            output=output,
            metadata=sample_video_metadata,
            base_dir=tmp_path / "output",
            cleanup_work_dir=False,
        )
        assert result.frames_dir is not None
        assert result.frames_dir.exists()

    def test_writes_html_viewer_and_source_video(
        self, tmp_path, sample_note_section, sample_video_metadata, sample_transcript
    ):
        video_path = tmp_path / "work" / "source.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"video")
        metadata = sample_video_metadata.model_copy(update={"video_path": video_path})

        output = FinalOutput(
            video_id=metadata.video_id,
            title=metadata.title,
            channel=metadata.channel,
            duration_seconds=metadata.duration_seconds,
            sections=[sample_note_section],
            markdown_content="# Notes\n",
            video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )
        result = write(
            output=output,
            metadata=metadata,
            base_dir=tmp_path / "output",
            transcript=sample_transcript,
            html_enabled=True,
            cleanup_work_dir=False,
        )

        assert result.html_path is not None
        assert result.html_path.exists()
        assert result.notes_html_path is not None
        assert result.notes_html_path.exists()
        assert result.source_video_path is not None
        assert result.source_video_path.exists()
        assert "Transcript Pane" in result.html_path.read_text(encoding="utf-8")
