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
