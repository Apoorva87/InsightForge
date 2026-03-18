"""Unit tests for Stage 1 — Ingestion."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from insightforge.stages.ingestion import IngestionError, _find_downloaded_file, _sanitise_filename


class TestFindDownloadedFile:
    def test_finds_mp4(self, tmp_path):
        (tmp_path / "abc123.mp4").touch()
        result = _find_downloaded_file(tmp_path, "abc123")
        assert result.name == "abc123.mp4"

    def test_fallback_to_first_file(self, tmp_path):
        (tmp_path / "abc123.mkv").touch()
        result = _find_downloaded_file(tmp_path, "xyz")
        assert result.exists()

    def test_raises_when_empty(self, tmp_path):
        with pytest.raises(IngestionError):
            _find_downloaded_file(tmp_path, "missing")


def test_sanitise_filename():
    from insightforge.stages.ingestion import _sanitise_filename
    assert "/" not in _sanitise_filename("My Video: Part 1/2")
    assert _sanitise_filename("  hello  ") == "hello"
