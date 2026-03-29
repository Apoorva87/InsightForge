"""Tests for pipeline helper functions."""

from __future__ import annotations

from unittest.mock import Mock

from insightforge.models.output import NoteSection
from insightforge.pipeline import _build_audio_text, _configure_logging, _leaf_sections


def _make_section(sid: str, *, subsections: list[NoteSection] | None = None) -> NoteSection:
    return NoteSection(
        section_id=sid,
        chunk_id="chunk_0000",
        timestamp_start=0.0,
        timestamp_end=10.0,
        heading=f"Heading {sid}",
        summary="Summary.",
        subsections=subsections or [],
    )


class TestLeafSections:
    def test_flat_sections_returned_as_is(self):
        sections = [_make_section("s0"), _make_section("s1")]
        leaves = _leaf_sections(sections)
        assert [s.section_id for s in leaves] == ["s0", "s1"]

    def test_nested_returns_only_leaves(self):
        child_a = _make_section("child_a")
        child_b = _make_section("child_b")
        parent = _make_section("parent", subsections=[child_a, child_b])
        leaves = _leaf_sections([parent])
        assert [s.section_id for s in leaves] == ["child_a", "child_b"]

    def test_mixed_flat_and_nested(self):
        flat = _make_section("flat")
        child = _make_section("child")
        parent = _make_section("parent", subsections=[child])
        leaves = _leaf_sections([flat, parent])
        assert [s.section_id for s in leaves] == ["flat", "child"]

    def test_deeply_nested(self):
        grandchild = _make_section("gc")
        child = _make_section("child", subsections=[grandchild])
        parent = _make_section("parent", subsections=[child])
        leaves = _leaf_sections([parent])
        assert [s.section_id for s in leaves] == ["gc"]

    def test_empty_input(self):
        assert _leaf_sections([]) == []


class TestBuildAudioText:
    def test_level_zero_returns_summary_only(self):
        sections = [_make_section("s0"), _make_section("s1")]
        result = _build_audio_text(0.0, "Executive overview.", sections, None)
        assert result == "Executive overview."
        assert "Heading" not in result

    def test_level_zero_no_summary_falls_back_to_headings(self):
        sections = [_make_section("s0"), _make_section("s1")]
        result = _build_audio_text(0.0, "", sections, None)
        assert "Heading s0" in result
        assert "Heading s1" in result

    def test_intermediate_level_includes_summary_and_headings(self):
        sections = [_make_section("s0")]
        result = _build_audio_text(0.5, "Overview.", sections, None)
        assert "Overview." in result
        assert "Heading s0" in result

    def test_intermediate_level_no_summary_still_works(self):
        sections = [_make_section("s0")]
        result = _build_audio_text(0.5, "", sections, None)
        assert "Overview" not in result
        assert "Heading s0" in result


def test_configure_logging_uses_debug_when_runtime_verbose(monkeypatch) -> None:
    mock_setup = Mock()
    monkeypatch.setattr("insightforge.pipeline.setup_logging", mock_setup)

    _configure_logging({
        "logging": {"level": "INFO", "format": "text"},
        "_runtime": {"verbose": True},
    })

    mock_setup.assert_called_once_with(level="DEBUG", format="text")
