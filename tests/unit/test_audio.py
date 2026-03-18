"""Unit tests for post-processing audio summary generation."""

from __future__ import annotations

from insightforge.audio import (
    build_audio_text_from_saved_output,
    extract_executive_summary,
    extract_transcript_body,
    parse_sections,
)


def test_extract_executive_summary():
    notes = """# Title

## Executive Summary

This is the summary.

**Key highlights:**
- One
- Two

---

## Section A
"""
    summary = extract_executive_summary(notes)
    assert "This is the summary." in summary
    assert "One" in summary


def test_parse_sections_prefers_leaf_sections():
    notes = """# Title

## Parent Topic

Parent summary.

### Child One

Child one summary.
- Point one

### Child Two

Child two summary.
- Point two
"""
    sections = parse_sections(notes)
    assert [section.heading for section in sections] == ["Parent Topic", "Child One", "Child Two"]
    audio_text = build_audio_text_from_saved_output(0.5, "", sections, "")
    assert "Child one summary." in audio_text
    assert "Parent summary." not in audio_text


def test_extract_transcript_body():
    transcript = """# Title
# Channel: Test

[00:00] Hello world
[00:05] Another line
"""
    body = extract_transcript_body(transcript)
    assert body == "Hello world Another line"
