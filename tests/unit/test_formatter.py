"""Unit tests for Stage 8 — Output Formatter."""

from __future__ import annotations

import pytest

from insightforge.stages.formatter import run, _heading_to_anchor, _render_header


class TestFormatterRun:
    def test_produces_markdown_content(self, sample_note_section, sample_video_metadata):
        output = run(
            sections=[sample_note_section],
            metadata=sample_video_metadata,
        )
        assert len(output.markdown_content) > 0
        assert "##" in output.markdown_content

    def test_title_in_markdown(self, sample_note_section, sample_video_metadata):
        output = run(sections=[sample_note_section], metadata=sample_video_metadata)
        assert sample_video_metadata.title in output.markdown_content

    def test_timestamp_index_included(self, sample_note_section, sample_video_metadata):
        output = run(
            sections=[sample_note_section],
            metadata=sample_video_metadata,
            include_timestamp_index=True,
        )
        assert "Contents" in output.markdown_content

    def test_timestamp_index_excluded(self, sample_note_section, sample_video_metadata):
        output = run(
            sections=[sample_note_section],
            metadata=sample_video_metadata,
            include_timestamp_index=False,
        )
        assert "Contents" not in output.markdown_content

    def test_key_points_in_output(self, sample_note_section, sample_video_metadata):
        output = run(sections=[sample_note_section], metadata=sample_video_metadata)
        for point in sample_note_section.key_points:
            assert point in output.markdown_content

    def test_ends_with_newline(self, sample_note_section, sample_video_metadata):
        output = run(sections=[sample_note_section], metadata=sample_video_metadata)
        assert output.markdown_content.endswith("\n")


class TestHeadingToAnchor:
    def test_lowercases(self):
        assert _heading_to_anchor("Hello World") == "hello-world"

    def test_removes_problematic_chars(self):
        assert "[" not in _heading_to_anchor("Title [With] Brackets")
        assert "|" not in _heading_to_anchor("Title | With Pipe")

    def test_replaces_spaces_with_dashes(self):
        assert _heading_to_anchor("My Section Title") == "my-section-title"
