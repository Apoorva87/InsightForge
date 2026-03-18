"""Unit tests for Stage 2 — Transcript."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from insightforge.models.transcript import TranscriptResult, TranscriptSegment
from insightforge.stages.transcript import _try_youtube_transcript


class TestYouTubeTranscriptFetch:
    def test_returns_none_when_api_not_installed(self):
        with patch.dict("sys.modules", {"youtube_transcript_api": None}):
            result = _try_youtube_transcript("dQw4w9WgXcQ")
        assert result is None

    def test_parses_valid_api_response(self):
        fake_api_entry = [
            {"start": 0.0, "duration": 5.0, "text": "Hello world"},
            {"start": 5.5, "duration": 4.5, "text": "This is a test"},
        ]
        mock_yta_class = MagicMock()
        mock_yta_class.get_transcript.return_value = fake_api_entry

        mock_module = MagicMock()
        mock_module.YouTubeTranscriptApi = mock_yta_class
        mock_module.NoTranscriptFound = Exception
        mock_module.TranscriptsDisabled = Exception

        with patch.dict("sys.modules", {"youtube_transcript_api": mock_module}):
            result = _try_youtube_transcript("test_id")

        assert result is not None
        assert len(result.segments) == 2
        assert result.segments[0].text == "Hello world"
        assert result.source == "youtube_manual"
