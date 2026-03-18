"""Unit tests for static HTML viewer export."""

from __future__ import annotations

from pathlib import Path

from insightforge.models.output import FinalOutput
from insightforge.storage.html_export import _frame_caption, write_html_viewer


def test_write_html_viewer_includes_sections_transcript_and_assets(
    tmp_path,
    sample_note_section,
    sample_video_metadata,
    sample_transcript,
):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    frame_path = frames_dir / "frame_0000.jpg"
    frame_path.write_bytes(b"jpg")
    sample_note_section.frames[0:0] = []

    clip_dir = tmp_path / "clips"
    clip_dir.mkdir()
    clip_path = clip_dir / f"{sample_note_section.section_id}.mp4"
    clip_path.write_bytes(b"mp4")

    video_dir = tmp_path / "video"
    video_dir.mkdir()
    source_video = video_dir / "source.mp4"
    source_video.write_bytes(b"video")

    output = FinalOutput(
        video_id=sample_video_metadata.video_id,
        title=sample_video_metadata.title,
        channel=sample_video_metadata.channel,
        duration_seconds=sample_video_metadata.duration_seconds,
        video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        executive_summary="A concise overview.",
        sections=[sample_note_section],
        frames_dir=frames_dir,
        clips_dir=clip_dir,
        source_video_path=source_video,
    )

    html_path, notes_path = write_html_viewer(
        output=output,
        metadata=sample_video_metadata,
        transcript=sample_transcript,
        output_dir=tmp_path / "output",
    )

    html = html_path.read_text(encoding="utf-8")
    notes_html = notes_path.read_text(encoding="utf-8")
    assert "Transcript Pane" in html
    assert sample_note_section.heading in html
    assert "A concise overview." in html
    assert "../video/source.mp4" in html
    assert "Open notes-only HTML" in html
    assert "current-subsections" in html
    assert "syncTranscriptHighlight" in html
    assert "transcript-line active" in html or ".transcript-line.active" in html
    assert "Show Explanatory Snapshots" in html
    assert "buildAnnotatedPoints" in html
    assert "weightedJaccard" in html
    assert "THRESHOLD" in html
    assert "findActiveSectionByTime" in html
    assert "chat-web-search" in html
    assert "chat-context-length" in html
    assert "chat-reset" in html
    assert "data-tooltip" in html
    assert "getEffectiveFrames" in html
    assert "content_score" in html
    assert "Analyzing transcript + searching web" in html
    assert 'seekTo(item.frame.timestamp, true)' in html
    assert "startTranscriptTracking" in html
    assert "requestAnimationFrame" in html
    assert 'if (transcriptMode === "section"' in html
    assert 'selectSection(activeSection.id, false);' in html
    assert "sourceVideo.addEventListener(\"play\", startTranscriptTracking)" in html
    # Verify event listeners wrap syncTranscriptHighlight in arrow functions
    # to prevent the Event object from being passed as overrideTime
    assert 'addEventListener("timeupdate", () => syncTranscriptHighlight())' in html
    assert 'addEventListener("seeking", () => syncTranscriptHighlight())' in html
    assert 'addEventListener("seeked", () => syncTranscriptHighlight())' in html
    assert 'addEventListener("loadedmetadata", () => syncTranscriptHighlight())' in html
    # Ensure the bare function reference pattern is NOT used for these events
    assert 'addEventListener("timeupdate", syncTranscriptHighlight)' not in html
    assert "<h1>Introduction to Python Decorators</h1>" in notes_html


def test_frame_caption_uses_neighboring_transcript_context(sample_transcript):
    caption = _frame_caption(6.0, sample_transcript)

    assert caption
    assert "Hello and welcome to this tutorial" in caption
    assert "Today we are going to learn about Python decorators" in caption
