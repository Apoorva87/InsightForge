"""Stage 8 — Output Formatter: assemble NoteSection list into final Markdown."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from insightforge.models.frame import Frame
from insightforge.models.output import FinalOutput, NoteSection
from insightforge.models.transcript import TranscriptResult
from insightforge.models.video import VideoMetadata
from insightforge.utils.logging import get_logger

logger = get_logger(__name__)


def run(
    sections: list[NoteSection],
    metadata: VideoMetadata,
    frames_dir: Optional[Path] = None,
    embed_frames_inline: bool = True,
    include_timestamp_index: bool = True,
    markdown_flavor: str = "github",
    video_url: Optional[str] = None,
    executive_summary: str = "",
    transcript: Optional[TranscriptResult] = None,
    clips_dir: Optional[Path] = None,
) -> FinalOutput:
    """Assemble all NoteSection objects into a FinalOutput with rendered Markdown.

    Also generates a separate transcript.md with raw transcript text and inline
    frames per section.
    """
    lines: list[str] = []

    lines.extend(_render_header(metadata))
    lines.append("")

    if include_timestamp_index and sections:
        lines.extend(_render_timestamp_index(sections))
        lines.append("")

    if executive_summary:
        lines.extend(_render_executive_summary(executive_summary))
        lines.append("")

    for section in sections:
        lines.extend(
            _render_section(section, frames_dir, embed_frames_inline, clips_dir)
        )
        lines.append("")

    markdown = "\n".join(lines).rstrip() + "\n"
    logger.info("Formatter: assembled %d lines of Markdown (notes)", len(lines))

    # Generate transcript.md content
    transcript_md = ""
    if transcript and sections:
        transcript_md = _render_transcript_md(
            sections, metadata, transcript, frames_dir, clips_dir
        )
        logger.info("Formatter: generated transcript.md")

    return FinalOutput(
        video_id=metadata.video_id,
        title=metadata.title,
        channel=metadata.channel,
        duration_seconds=metadata.duration_seconds,
        executive_summary=executive_summary,
        sections=sections,
        markdown_content=markdown,
        transcript_md_content=transcript_md,
        frames_dir=frames_dir,
        clips_dir=clips_dir,
    )


def _render_header(metadata: VideoMetadata) -> list[str]:
    """Render the document header block."""
    lines = [
        f"# {metadata.title}",
        "",
        f"**Channel:** {metadata.channel}  ",
        f"**Duration:** {metadata.duration_human}  ",
    ]
    if metadata.upload_date:
        date = metadata.upload_date
        try:
            formatted = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        except Exception:
            formatted = date
        lines.append(f"**Uploaded:** {formatted}  ")
    lines.append(f"**Video ID:** `{metadata.video_id}`  ")
    lines.append("")
    lines.append("---")
    return lines


def _render_executive_summary(summary: str) -> list[str]:
    """Render the executive summary block."""
    lines = ["## Executive Summary", "", summary, "", "---"]
    return lines


def _render_timestamp_index(sections: list[NoteSection]) -> list[str]:
    """Render a clickable table of contents with timestamps."""
    lines = ["## Contents", ""]
    for section in sections:
        anchor = _heading_to_anchor(section.heading)
        lines.append(
            f"- {section.timestamp_str} — [{section.heading}](#{anchor})"
        )
    return lines


def _render_section(
    section: NoteSection,
    frames_dir: Optional[Path],
    embed_frames_inline: bool,
    clips_dir: Optional[Path] = None,
) -> list[str]:
    """Render a single NoteSection to Markdown lines with inline frames."""
    ts_display = f"*{section.timestamp_str}*"

    lines = [
        f"## {section.heading}",
        "",
        ts_display,
        "",
    ]

    # Local video clip embed
    if clips_dir:
        clip_name = f"section_{section.section_id.split('_')[-1]}.mp4"
        clip_rel = Path("clips") / clip_name
        lines.append(f'<video controls width="100%" src="{clip_rel}"></video>')
        lines.append("")

    lines.append(section.summary)
    lines.append("")

    # Interleave frames with key_points based on timestamp
    if embed_frames_inline and section.frames and section.key_points:
        lines.extend(
            _interleave_frames_with_points(section, frames_dir)
        )
    else:
        if section.key_points:
            for point in section.key_points:
                lines.append(f"- {point}")
            lines.append("")
        if embed_frames_inline and section.frames:
            sorted_frames = sorted(section.frames, key=lambda f: f.timestamp)
            for frame in sorted_frames:
                rel_path = _frame_rel_path(frame, frames_dir)
                lines.append(f"![Frame at {frame.timestamp_str}]({rel_path})")
            lines.append("")

    return lines


def _interleave_frames_with_points(
    section: NoteSection, frames_dir: Optional[Path]
) -> list[str]:
    """Interleave frames between key_points based on timestamp alignment.

    Strategy: divide the section's time range into equal slots (one per key_point).
    After each key_point, insert any frames whose timestamps fall in that slot.
    """
    lines: list[str] = []
    sorted_frames = sorted(section.frames, key=lambda f: f.timestamp)
    n_points = len(section.key_points)
    section_start = section.timestamp_start
    section_end = section.timestamp_end
    slot_duration = (section_end - section_start) / max(n_points, 1)

    frame_idx = 0
    for i, point in enumerate(section.key_points):
        lines.append(f"- {point}")

        slot_end = section_start + (i + 1) * slot_duration
        inserted = False
        while frame_idx < len(sorted_frames):
            frame = sorted_frames[frame_idx]
            if frame.timestamp < slot_end or i == n_points - 1:
                if not inserted:
                    lines.append("")
                    inserted = True
                rel_path = _frame_rel_path(frame, frames_dir)
                lines.append(f"  ![Frame at {frame.timestamp_str}]({rel_path})")
                frame_idx += 1
            else:
                break
        if inserted:
            lines.append("")

    if lines and lines[-1] != "":
        lines.append("")
    return lines


# ---------- Transcript Markdown ----------


def _render_transcript_md(
    sections: list[NoteSection],
    metadata: VideoMetadata,
    transcript: TranscriptResult,
    frames_dir: Optional[Path],
    clips_dir: Optional[Path] = None,
) -> str:
    """Generate a full transcript.md with raw transcript text and inline frames per section."""
    lines: list[str] = [
        f"# {metadata.title} — Full Transcript",
        "",
        f"**Channel:** {metadata.channel}  ",
        f"**Duration:** {metadata.duration_human}  ",
        f"**Segments:** {len(transcript.segments)} | **Words:** {transcript.word_count}  ",
        "",
        "---",
        "",
    ]

    # Table of contents
    lines.append("## Sections")
    lines.append("")
    for section in sections:
        anchor = _heading_to_anchor(section.heading)
        lines.append(f"- {section.timestamp_str} — [{section.heading}](#{anchor})")
    lines.append("")

    # Each section: heading, clip, then raw transcript with interleaved frames
    for section in sections:
        lines.append(f"## {section.heading}")
        lines.append("")
        lines.append(f"*{section.timestamp_str} — {section.timestamp_end_str}*")
        lines.append("")

        # Local video clip
        if clips_dir:
            clip_name = f"section_{section.section_id.split('_')[-1]}.mp4"
            clip_rel = Path("clips") / clip_name
            lines.append(f'<video controls width="100%" src="{clip_rel}"></video>')
            lines.append("")

        # Get transcript segments for this section's time range
        section_segments = [
            seg for seg in transcript.segments
            if seg.start >= section.timestamp_start - 0.5
            and seg.start < section.timestamp_end + 0.5
        ]

        # Get sorted frames for this section
        sorted_frames = (
            sorted(section.frames, key=lambda f: f.timestamp)
            if section.frames else []
        )

        # Group segments into blurbs split by frame positions.
        # Each blurb gets one timestamp at the start, then continuous text,
        # then the frame(s) that follow.
        frame_times = [f.timestamp for f in sorted_frames]
        blurbs = _split_segments_into_blurbs(section_segments, frame_times)

        frame_idx = 0
        for blurb_segments in blurbs:
            if not blurb_segments:
                continue
            # One timestamp for the blurb
            lines.append(f"**[{blurb_segments[0].timestamp_str}]**")
            lines.append("")
            # Continuous text paragraph
            text = " ".join(seg.text for seg in blurb_segments)
            lines.append(text)
            lines.append("")
            # Insert frames that fall between this blurb's end and the next blurb
            blurb_end = blurb_segments[-1].end
            while frame_idx < len(sorted_frames):
                frame = sorted_frames[frame_idx]
                if frame.timestamp <= blurb_end + 1.5:
                    rel_path = _frame_rel_path(frame, frames_dir)
                    lines.append(f"![Frame at {frame.timestamp_str}]({rel_path})")
                    lines.append("")
                    frame_idx += 1
                else:
                    break

        # Flush remaining frames
        while frame_idx < len(sorted_frames):
            frame = sorted_frames[frame_idx]
            rel_path = _frame_rel_path(frame, frames_dir)
            lines.append(f"![Frame at {frame.timestamp_str}]({rel_path})")
            lines.append("")
            frame_idx += 1

        lines.append("---")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _split_segments_into_blurbs(
    segments: list, frame_times: list[float]
) -> list[list]:
    """Split transcript segments into blurbs at frame boundaries.

    Each blurb is a group of consecutive segments. A new blurb starts
    whenever a frame timestamp falls between two segments.
    """
    if not segments:
        return []
    if not frame_times:
        return [segments]

    blurbs: list[list] = []
    current_blurb: list = []

    for seg in segments:
        # Check if any frame falls between the previous segment's end and this one's start
        if current_blurb:
            prev_end = current_blurb[-1].end
            has_frame_between = any(
                prev_end - 1.0 <= ft <= seg.start + 1.0 for ft in frame_times
            )
            if has_frame_between:
                blurbs.append(current_blurb)
                current_blurb = []

        current_blurb.append(seg)

    if current_blurb:
        blurbs.append(current_blurb)

    return blurbs


# ---------- Helpers ----------


def _frame_rel_path(frame: Frame, frames_dir: Optional[Path]) -> str:
    """Return the relative path string for a frame image."""
    if frames_dir is not None:
        return str(Path("frames") / frame.path.name)
    return str(frame.path)


def _heading_to_anchor(heading: str) -> str:
    """Convert a heading to a Markdown anchor compatible with Obsidian and GitHub."""
    anchor = heading.lower().strip()
    anchor = re.sub(r"[#\[\](){}|\\^`]", "", anchor)
    anchor = re.sub(r"\s+", "-", anchor).strip("-")
    return anchor
