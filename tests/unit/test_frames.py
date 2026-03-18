"""Unit tests for Stage 5 — Frame Extraction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from insightforge.models.frame import FrameSet
from insightforge.stages.frames import run


class TestFramesRun:
    def test_returns_empty_frameset_when_ffmpeg_missing(self, tmp_path, sample_chunk_batch):
        with patch("insightforge.stages.frames.ffmpeg_utils.check_ffmpeg", return_value=False):
            result = run(
                video_path=tmp_path / "fake.mp4",
                output_dir=tmp_path / "frames",
                chunk_batch=sample_chunk_batch,
            )
        assert isinstance(result, FrameSet)
        assert len(result.frames) == 0

    def test_returns_empty_frameset_on_error(self, tmp_path, sample_chunk_batch):
        with patch("insightforge.stages.frames.ffmpeg_utils.check_ffmpeg", return_value=True):
            with patch(
                "insightforge.stages.frames.ffmpeg_utils.extract_frames_scene_change",
                side_effect=RuntimeError("ffmpeg failed"),
            ):
                with pytest.raises(RuntimeError):
                    run(
                        video_path=tmp_path / "fake.mp4",
                        output_dir=tmp_path / "frames",
                        chunk_batch=sample_chunk_batch,
                        extraction_mode="scene_change",
                    )

    def test_invalid_extraction_mode_raises(self, tmp_path, sample_chunk_batch):
        with patch("insightforge.stages.frames.ffmpeg_utils.check_ffmpeg", return_value=True):
            with pytest.raises(ValueError, match="Unknown extraction_mode"):
                run(
                    video_path=tmp_path / "fake.mp4",
                    output_dir=tmp_path / "frames",
                    chunk_batch=sample_chunk_batch,
                    extraction_mode="invalid_mode",
                )
