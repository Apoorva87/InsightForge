"""Tests for Ollama provider helper functions."""

from __future__ import annotations

import json

from insightforge.llm.ollama_provider import _extract_from_thinking, _find_json_objects


class TestFindJsonObjects:
    def test_flat_object(self):
        text = 'some text {"score": 0.8} more text'
        assert _find_json_objects(text) == ['{"score": 0.8}']

    def test_nested_object(self):
        text = 'thinking {"outer": {"inner": 1}} done'
        objs = _find_json_objects(text)
        assert len(objs) == 1
        assert json.loads(objs[0]) == {"outer": {"inner": 1}}

    def test_multiple_objects(self):
        text = '{"a": 1} text {"b": 2}'
        assert len(_find_json_objects(text)) == 2

    def test_escaped_braces_in_string(self):
        text = r'{"text": "curly \"{\" brace"}'
        objs = _find_json_objects(text)
        assert len(objs) == 1

    def test_no_json(self):
        assert _find_json_objects("no json here") == []

    def test_multiline_json(self):
        text = '{\n  "heading": "Test",\n  "summary": "A summary"\n}'
        objs = _find_json_objects(text)
        assert len(objs) == 1
        assert json.loads(objs[0])["heading"] == "Test"

    def test_array_values(self):
        text = '{"key_points": ["a", "b", "c"]}'
        objs = _find_json_objects(text)
        assert len(objs) == 1
        assert json.loads(objs[0])["key_points"] == ["a", "b", "c"]


class TestExtractFromThinking:
    def test_extracts_score_json(self):
        thinking = "Let me think... the score should be 0.8\n{'score': 0.8}\nWait, actually:\n" + json.dumps({"score": 0.75})
        result = _extract_from_thinking(thinking)
        parsed = json.loads(result)
        assert parsed["score"] == 0.75

    def test_prefers_heading_json_over_score(self):
        thinking = (
            json.dumps({"score": 0.5})
            + "\nOkay so the section is:\n"
            + json.dumps({"heading": "Intro", "summary": "An intro."})
        )
        result = _extract_from_thinking(thinking)
        parsed = json.loads(result)
        assert "heading" in parsed

    def test_extracts_nested_json(self):
        nested = {"heading": "Topic", "metadata": {"source": "chunk_0001"}}
        thinking = f"After analysis:\n{json.dumps(nested)}\nDone."
        result = _extract_from_thinking(thinking)
        parsed = json.loads(result)
        assert parsed["heading"] == "Topic"
        assert parsed["metadata"]["source"] == "chunk_0001"

    def test_score_pattern_fallback(self):
        thinking = "I think the importance is moderate.\nScore: 0.65\n"
        result = _extract_from_thinking(thinking)
        parsed = json.loads(result)
        assert parsed["score"] == 0.65

    def test_bare_decimal_fallback(self):
        thinking = "Hmm, this is fairly important.\n0.72"
        result = _extract_from_thinking(thinking)
        parsed = json.loads(result)
        assert parsed["score"] == 0.72

    def test_last_line_fallback(self):
        thinking = "No structured output here.\nJust this last line."
        result = _extract_from_thinking(thinking)
        assert result == "Just this last line."

    def test_empty_thinking(self):
        assert _extract_from_thinking("") == ""
