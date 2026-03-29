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
            _render_section(section, frames_dir, embed_frames_inline, clips_dir, level=2)
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
        video_url=video_url,
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
        lines.extend(_render_timestamp_index_entry(section, indent=0))
    return lines


def _render_timestamp_index_entry(section: NoteSection, indent: int) -> list[str]:
    prefix = "  " * indent
    anchor = _heading_to_anchor(section.heading)
    lines = [f"{prefix}- {section.timestamp_str} — [{section.heading}](#{anchor})"]
    for subsection in section.subsections:
        lines.extend(_render_timestamp_index_entry(subsection, indent + 1))
    return lines


def _render_section(
    section: NoteSection,
    frames_dir: Optional[Path],
    embed_frames_inline: bool,
    clips_dir: Optional[Path] = None,
    level: int = 2,
) -> list[str]:
    """Render a single NoteSection to Markdown lines with inline frames."""
    ts_display = f"*{section.timestamp_str}*"
    heading_prefix = "#" * max(2, min(level, 6))

    lines = [
        f"{heading_prefix} {section.heading}",
        "",
        ts_display,
        "",
    ]

    # Local video clip embed
    if clips_dir and section.is_leaf:
        clip_name = f"{section.section_id}.mp4"
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
                if rel_path:
                    lines.append(f"![Frame at {frame.timestamp_str}]({rel_path})")
            lines.append("")

    # Educational artifacts — only rendered when present (educational mode)
    lines.extend(_render_educational_artifacts(section))

    for subsection in section.subsections:
        lines.extend(
            _render_section(
                subsection,
                frames_dir=frames_dir,
                embed_frames_inline=embed_frames_inline,
                clips_dir=clips_dir,
                level=level + 1,
            )
        )
        lines.append("")

    return lines


def _render_educational_artifacts(section: NoteSection) -> list[str]:
    """Render formulas, code snippets, and examples extracted from the transcript."""
    lines: list[str] = []

    if section.formulas:
        lines.append("**Formulas:**")
        lines.append("")
        for formula in section.formulas:
            # Render as a math block if it contains LaTeX, otherwise inline
            if formula.startswith("$") or "\\" in formula:
                lines.append(f"$$\n{formula.strip('$').strip()}\n$$")
            else:
                lines.append(f"- ${formula}$")
        lines.append("")

    if section.code_snippets:
        lines.append("**Code:**")
        lines.append("")
        for snippet in section.code_snippets:
            lines.append("```")
            lines.append(snippet)
            lines.append("```")
            lines.append("")

    if section.examples:
        lines.append("**Example:**")
        lines.append("")
        for example in section.examples:
            # Render as a blockquote for visual distinction
            for line in example.split("\n"):
                lines.append(f"> {line}")
            lines.append("")

    return lines


def _interleave_frames_with_points(
    section: NoteSection, frames_dir: Optional[Path]
) -> list[str]:
    """Interleave frames between key_points based on keyword matching.

    Strategy: match each frame's description/ocr_text to the most relevant
    key_point using keyword overlap. Place each frame after its matched point.
    Unmatched frames go after the last point.
    """
    lines: list[str] = []
    sorted_frames = sorted(section.frames, key=lambda f: f.timestamp)
    points = section.key_points

    if not sorted_frames:
        for point in points:
            lines.append(f"- {point}")
        lines.append("")
        return lines

    # Build keyword-based assignments: frame_index → point_index
    assignments = _match_frames_to_points(sorted_frames, points)

    # Group frames by assigned point
    point_frames: dict[int, list[Frame]] = {}
    unmatched: list[Frame] = []
    for fi, pi in assignments.items():
        if pi is not None:
            point_frames.setdefault(pi, []).append(sorted_frames[fi])
        else:
            unmatched.append(sorted_frames[fi])

    for i, point in enumerate(points):
        lines.append(f"- {point}")
        matched = point_frames.get(i, [])
        if matched:
            lines.append("")
            for frame in sorted(matched, key=lambda f: f.timestamp):
                rel_path = _frame_rel_path(frame, frames_dir)
                if rel_path:
                    caption = frame.description or f"Frame at {frame.timestamp_str}"
                    lines.append(f"  ![{caption}]({rel_path})")
                    if frame.ocr_text:
                        lines.extend(_render_ocr_text_md(frame.ocr_text))
            lines.append("")

    # Append unmatched frames at end
    if unmatched:
        lines.append("")
        for frame in sorted(unmatched, key=lambda f: f.timestamp):
            rel_path = _frame_rel_path(frame, frames_dir)
            if rel_path:
                caption = frame.description or f"Frame at {frame.timestamp_str}"
                lines.append(f"![{caption}]({rel_path})")
                if frame.ocr_text:
                    lines.extend(_render_ocr_text_md(frame.ocr_text))
        lines.append("")

    if lines and lines[-1] != "":
        lines.append("")
    return lines


def _match_frames_to_points(
    frames: list[Frame], points: list[str]
) -> dict[int, Optional[int]]:
    """Match frames to key_points by keyword overlap on description + ocr_text."""
    if not points:
        return {i: None for i in range(len(frames))}

    def _tokenize(text: str) -> set[str]:
        stopwords = {
            "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
            "to", "of", "for", "in", "on", "at", "by", "with", "from", "as",
            "it", "its", "this", "that", "these", "those", "we", "you", "they",
        }
        words = set(re.findall(r"[a-zA-Z0-9]{3,}", text.lower()))
        return words - stopwords

    point_tokens = [_tokenize(p) for p in points]
    assignments: dict[int, Optional[int]] = {}
    used_points: set[int] = set()

    for fi, frame in enumerate(frames):
        frame_text = " ".join(filter(None, [frame.description, frame.ocr_text]))
        frame_tokens = _tokenize(frame_text)
        if not frame_tokens:
            assignments[fi] = None
            continue

        best_pi = None
        best_score = 0.0
        for pi, pt in enumerate(point_tokens):
            if not pt:
                continue
            overlap = len(frame_tokens & pt)
            union = len(frame_tokens | pt)
            score = overlap / union if union > 0 else 0.0
            if score > best_score:
                best_score = score
                best_pi = pi

        if best_score >= 0.05 and best_pi is not None:
            assignments[fi] = best_pi
        else:
            assignments[fi] = None

    return assignments


def _render_ocr_text_md(ocr_text: str) -> list[str]:
    """Render OCR text as markdown — detect formulas vs code vs plain text."""
    lines: list[str] = []
    text = ocr_text.strip()
    if not text:
        return lines

    # Check if it looks like code (has indentation, braces, semicolons, etc.)
    code_indicators = any(c in text for c in ["{", "}", ";", "def ", "class ", "import ", "=>", "->"])
    has_latex = "$" in text or "\\" in text

    if code_indicators and not has_latex:
        lines.append("  ```")
        lines.append(f"  {text}")
        lines.append("  ```")
    elif has_latex:
        lines.append(f"  > {text}")
    else:
        lines.append(f"  > *{text}*")
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
    transcript_start = transcript.segments[0].start if transcript.segments else 0.0
    transcript_end = transcript.segments[-1].end if transcript.segments else 0.0
    blocks = _build_transcript_blocks_for_range(sections, transcript_start, transcript_end)

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
        lines.extend(_render_timestamp_index_entry(section, indent=0))
    lines.append("")

    # Sections and transcript blocks, preserving hierarchy while keeping full coverage
    for block in blocks:
        lines.extend(
            _render_transcript_block(
                block=block,
                transcript=transcript,
                frames_dir=frames_dir,
                clips_dir=clips_dir,
                level=2,
            )
        )
        lines.append("---")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _build_transcript_blocks_for_range(
    sections: list[NoteSection],
    range_start: float,
    range_end: float,
) -> list[dict[str, object]]:
    """Build non-overlapping blocks for a time range, preserving section hierarchy."""
    sorted_sections = sorted(
        sections,
        key=lambda s: (s.timestamp_start, s.timestamp_end, s.section_id),
    )

    blocks: list[dict[str, object]] = []
    cursor = range_start

    for index, section in enumerate(sorted_sections):
        section_start = max(cursor, section.timestamp_start)
        next_start = (
            sorted_sections[index + 1].timestamp_start
            if index + 1 < len(sorted_sections)
            else range_end
        )
        if next_start <= section_start:
            next_start = range_end
        section_end = min(section.timestamp_end, next_start, range_end)

        if cursor < section_start:
            blocks.append(_make_transcript_block(cursor, section_start, None))

        if section_end > section_start:
            blocks.append(_make_transcript_block(section_start, section_end, section))
            cursor = section_end
        else:
            cursor = max(cursor, section_start)

    if cursor < range_end:
        blocks.append(_make_transcript_block(cursor, range_end, None))

    return [block for block in blocks if block["end"] > block["start"]]


def _leaf_sections(sections: list[NoteSection]) -> list[NoteSection]:
    leaves: list[NoteSection] = []
    for section in sections:
        leaves.extend(section.leaf_sections())
    return leaves


def _make_transcript_block(
    start: float,
    end: float,
    section: Optional[NoteSection],
) -> dict[str, object]:
    """Create a transcript block descriptor."""
    heading = section.heading if section is not None else f"Transcript {NoteSection._format_time(start)}"
    return {
        "heading": heading,
        "start": start,
        "end": end,
        "timestamp_str": NoteSection._format_time(start),
        "timestamp_end_str": NoteSection._format_time(end),
        "section": section,
    }


def _render_transcript_block(
    block: dict[str, object],
    transcript: TranscriptResult,
    frames_dir: Optional[Path],
    clips_dir: Optional[Path],
    level: int,
) -> list[str]:
    """Render one transcript block, preserving parent/sub-section hierarchy."""
    section = block["section"]
    if section is None:
        return _render_leaf_transcript_block(
            heading=str(block["heading"]),
            start=float(block["start"]),
            end=float(block["end"]),
            transcript=transcript,
            frames_dir=frames_dir,
            section=None,
            level=level,
            clips_dir=clips_dir,
        )

    if section.is_leaf:
        return _render_leaf_transcript_block(
            heading=section.heading,
            start=float(block["start"]),
            end=float(block["end"]),
            transcript=transcript,
            frames_dir=frames_dir,
            section=section,
            level=level,
            clips_dir=clips_dir,
        )

    lines = [
        f"{'#' * max(2, min(level, 6))} {section.heading}",
        "",
        f"*{section.timestamp_str} — {section.timestamp_end_str}*",
        "",
    ]

    if section.summary:
        lines.append(section.summary)
        lines.append("")
    if section.key_points:
        for point in section.key_points:
            lines.append(f"- {point}")
        lines.append("")

    child_blocks = _build_transcript_blocks_for_range(
        section.subsections,
        section.timestamp_start,
        section.timestamp_end,
    )
    for child_block in child_blocks:
        lines.extend(
            _render_transcript_block(
                block=child_block,
                transcript=transcript,
                frames_dir=frames_dir,
                clips_dir=clips_dir,
                level=level + 1,
            )
        )
    return lines


def _render_leaf_transcript_block(
    heading: str,
    start: float,
    end: float,
    transcript: TranscriptResult,
    frames_dir: Optional[Path],
    section: Optional[NoteSection],
    level: int,
    clips_dir: Optional[Path],
) -> list[str]:
    """Render a transcript leaf block with raw transcript blurbs and optional frames/clips."""
    heading_prefix = "#" * max(2, min(level, 6))
    lines = [
        f"{heading_prefix} {heading}",
        "",
        f"*{NoteSection._format_time(start)} — {NoteSection._format_time(end)}*",
        "",
    ]

    if clips_dir and section is not None and section.is_leaf:
        clip_name = f"{section.section_id}.mp4"
        clip_rel = Path("clips") / clip_name
        lines.append(f'<video controls width="100%" src="{clip_rel}"></video>')
        lines.append("")

    section_segments = [
        seg for seg in transcript.segments
        if seg.start >= start
        and (
            seg.start < end
            or (
                end == transcript.segments[-1].end
                and seg.start <= end
            )
        )
    ]

    sorted_frames = (
        sorted(section.frames, key=lambda f: f.timestamp)
        if section and section.frames else []
    )
    frame_times = [f.timestamp for f in sorted_frames]
    blurbs = _split_segments_into_blurbs(section_segments, frame_times)

    frame_idx = 0
    for blurb_segments in blurbs:
        if not blurb_segments:
            continue
        lines.append(f"**[{blurb_segments[0].timestamp_str}]**")
        lines.append("")
        text = " ".join(seg.text for seg in blurb_segments)
        lines.append(text)
        lines.append("")
        blurb_end = blurb_segments[-1].end
        while frame_idx < len(sorted_frames):
            frame = sorted_frames[frame_idx]
            if frame.timestamp <= blurb_end + 1.5:
                rel_path = _frame_rel_path(frame, frames_dir)
                if rel_path:
                    lines.append(f"![Frame at {frame.timestamp_str}]({rel_path})")
                    lines.append("")
                frame_idx += 1
            else:
                break

    while frame_idx < len(sorted_frames):
        frame = sorted_frames[frame_idx]
        rel_path = _frame_rel_path(frame, frames_dir)
        if rel_path:
            lines.append(f"![Frame at {frame.timestamp_str}]({rel_path})")
            lines.append("")
        frame_idx += 1

    return lines


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


def _frame_rel_path(frame: Frame, frames_dir: Optional[Path]) -> Optional[str]:
    """Return the relative path string for a frame image."""
    if not frame.path.exists():
        logger.warning("Skipping missing frame reference: %s", frame.path)
        return None
    if frames_dir is not None:
        return str(Path("frames") / frame.path.name)
    return str(frame.path)


def _heading_to_anchor(heading: str) -> str:
    """Convert a heading to a Markdown anchor compatible with Obsidian and GitHub."""
    anchor = heading.lower().strip()
    anchor = re.sub(r"[#\[\](){}|\\^`]", "", anchor)
    anchor = re.sub(r"\s+", "-", anchor).strip("-")
    return anchor
