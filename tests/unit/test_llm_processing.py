"""Unit tests for Stage 7 — LLM Processing."""

from __future__ import annotations

import json

import pytest

from insightforge.models.output import NoteSection
from insightforge.stages.llm_processing import run, _parse_json_response, _fallback_section_data


class TestLLMProcessingRun:
    def test_returns_one_section_per_chunk(self, sample_scored_chunk, mock_llm_note):
        result = run(scored_chunks=[sample_scored_chunk], llm=mock_llm_note)
        assert len(result) == 1

    def test_section_has_heading(self, sample_scored_chunk, mock_llm_note):
        result = run(scored_chunks=[sample_scored_chunk], llm=mock_llm_note)
        assert result[0].heading != ""

    def test_section_has_key_points(self, sample_scored_chunk, mock_llm_note):
        result = run(scored_chunks=[sample_scored_chunk], llm=mock_llm_note)
        assert isinstance(result[0].key_points, list)

    def test_section_frames_attached(self, sample_scored_chunk, mock_llm_note, sample_frame_set):
        result = run(
            scored_chunks=[sample_scored_chunk],
            llm=mock_llm_note,
            frame_set=sample_frame_set,
        )
        # Frame at 6.0s is within 15s of chunk midpoint 6.0s
        assert len(result[0].frames) >= 1

    def test_fallback_on_bad_json(self, sample_scored_chunk):
        from tests.conftest import MockLLMProvider
        bad_llm = MockLLMProvider(response_text="not json at all !!!")
        result = run(scored_chunks=[sample_scored_chunk], llm=bad_llm)
        assert len(result) == 1
        assert result[0].heading != ""


class TestParseJsonResponse:
    def test_parses_clean_json(self):
        data = _parse_json_response('{"heading": "Test", "summary": "Sum", "key_points": []}')
        assert data["heading"] == "Test"

    def test_strips_markdown_fences(self):
        text = "```json\n{\"heading\": \"Test\"}\n```"
        data = _parse_json_response(text)
        assert data["heading"] == "Test"

    def test_raises_on_invalid(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_json_response("not json")
