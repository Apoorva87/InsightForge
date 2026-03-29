"""Unit tests for Stage 8 — Output Formatter."""

from __future__ import annotations

from pathlib import Path

import pytest

from insightforge.models.frame import Frame
from insightforge.models.output import NoteSection
from insightforge.stages.formatter import (
    _build_transcript_blocks_for_range,
    _heading_to_anchor,
    _render_header,
    run,
)


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

    def test_transcript_md_keeps_full_transcript_when_sections_skip_ranges(
        self, sample_video_metadata, sample_transcript
    ):
        sparse_section = NoteSection(
            section_id="section_0000",
            chunk_id="chunk_0000",
            timestamp_start=12.5,
            timestamp_end=20.0,
            heading="Middle Topic",
            summary="Summary",
            key_points=[],
        )

        output = run(
            sections=[sparse_section],
            metadata=sample_video_metadata,
            transcript=sample_transcript,
        )

        assert "Hello and welcome to this tutorial." in output.transcript_md_content
        assert "Here we define a wrapper function that adds behaviour." in output.transcript_md_content
        assert "## Transcript 00:00" in output.transcript_md_content

    def test_transcript_md_avoids_duplicate_overlap_from_sections(
        self, sample_video_metadata, sample_transcript
    ):
        first = NoteSection(
            section_id="section_0000",
            chunk_id="chunk_0000",
            timestamp_start=0.0,
            timestamp_end=20.0,
            heading="Part One",
            summary="Summary",
            key_points=[],
        )
        second = NoteSection(
            section_id="section_0001",
            chunk_id="chunk_0001",
            timestamp_start=12.5,
            timestamp_end=40.0,
            heading="Part Two",
            summary="Summary",
            key_points=[],
        )

        output = run(
            sections=[first, second],
            metadata=sample_video_metadata,
            transcript=sample_transcript,
        )

        assert output.transcript_md_content.count(
            "Decorators are a powerful feature in Python."
        ) == 1

    def test_nested_sections_render_subheadings(self, sample_video_metadata):
        child = NoteSection(
            section_id="section_0000_00",
            chunk_id="chunk_0000",
            timestamp_start=0.0,
            timestamp_end=10.0,
            heading="Child Section",
            summary="Child summary.",
            key_points=["Child point"],
        )
        parent = NoteSection(
            section_id="section_0000",
            chunk_id="chunk_0000",
            timestamp_start=0.0,
            timestamp_end=20.0,
            heading="Parent Topic",
            summary="Parent summary.",
            key_points=["Parent point"],
            subsections=[child],
        )

        output = run(sections=[parent], metadata=sample_video_metadata)

        assert "## Parent Topic" in output.markdown_content
        assert "### Child Section" in output.markdown_content

    def test_transcript_md_renders_parent_topics_and_nested_subsections(
        self, sample_video_metadata, sample_transcript
    ):
        child = NoteSection(
            section_id="section_0000_00",
            chunk_id="chunk_0000",
            timestamp_start=0.0,
            timestamp_end=12.0,
            heading="Child Section",
            summary="Child summary.",
            key_points=["Child point"],
        )
        parent = NoteSection(
            section_id="section_0000",
            chunk_id="chunk_0000",
            timestamp_start=0.0,
            timestamp_end=20.0,
            heading="Parent Topic",
            summary="Parent summary.",
            key_points=["Parent point"],
            subsections=[child],
        )

        output = run(
            sections=[parent],
            metadata=sample_video_metadata,
            transcript=sample_transcript,
        )

        assert "## Parent Topic" in output.transcript_md_content
        assert "Parent summary." in output.transcript_md_content
        assert "### Child Section" in output.transcript_md_content
        assert "Hello and welcome to this tutorial." in output.transcript_md_content

    def test_skips_missing_frame_paths_in_markdown(self, sample_note_section, sample_video_metadata, tmp_path):
        missing = Frame(
            frame_id="frame_missing",
            timestamp=6.0,
            path=tmp_path / "missing.jpg",
            description="Missing frame",
        )
        section = sample_note_section.model_copy(update={"frames": [missing]})

        output = run(sections=[section], metadata=sample_video_metadata, frames_dir=tmp_path)

        assert "missing.jpg" not in output.markdown_content


class TestTranscriptBlockOrdering:
    def test_uses_section_id_as_tiebreaker_for_equal_timestamps(self):
        later_id = NoteSection(
            section_id="section_0002",
            chunk_id="chunk_0002",
            timestamp_start=0.0,
            timestamp_end=10.0,
            heading="Later ID",
            summary="Summary",
        )
        earlier_id = NoteSection(
            section_id="section_0001",
            chunk_id="chunk_0001",
            timestamp_start=0.0,
            timestamp_end=10.0,
            heading="Earlier ID",
            summary="Summary",
        )

        blocks = _build_transcript_blocks_for_range([later_id, earlier_id], 0.0, 10.0)

        assert blocks[0]["section"].section_id == "section_0001"


class TestHeadingToAnchor:
    def test_lowercases(self):
        assert _heading_to_anchor("Hello World") == "hello-world"

    def test_removes_problematic_chars(self):
        assert "[" not in _heading_to_anchor("Title [With] Brackets")
        assert "|" not in _heading_to_anchor("Title | With Pipe")

    def test_replaces_spaces_with_dashes(self):
        assert _heading_to_anchor("My Section Title") == "my-section-title"
