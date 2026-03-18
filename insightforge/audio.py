"""Post-processing helpers for generating audio summaries from saved output."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from insightforge.utils import ffmpeg as ffmpeg_utils


class AudioSection(BaseModel):
    """Minimal section representation extracted from notes.md."""

    level: int
    heading: str
    summary: str = ""
    key_points: list[str] = []


def generate_audio_from_output_dir(output_dir: Path, level: float) -> Path:
    """Generate an audio summary from a saved InsightForge output directory."""
    output_dir = Path(output_dir)
    notes_path = output_dir / "notes.md"
    transcript_path = output_dir / "transcript.txt"

    if not notes_path.exists():
        raise FileNotFoundError(f"notes.md not found in {output_dir}")
    if not transcript_path.exists():
        raise FileNotFoundError(f"transcript.txt not found in {output_dir}")

    notes_text = notes_path.read_text(encoding="utf-8")
    transcript_text = transcript_path.read_text(encoding="utf-8")

    executive_summary = extract_executive_summary(notes_text)
    sections = parse_sections(notes_text)
    transcript_body = extract_transcript_body(transcript_text)
    audio_text = build_audio_text_from_saved_output(level, executive_summary, sections, transcript_body)

    audio_dir = output_dir / "audio_summary"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / _audio_filename(level)
    ffmpeg_utils.generate_audio_summary(audio_text, audio_path)
    return audio_path


def extract_executive_summary(notes_text: str) -> str:
    """Extract the executive summary section from notes.md."""
    match = re.search(
        r"^## Executive Summary\s*\n(?P<body>.*?)(?:\n---\n|\n## )",
        notes_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        return ""
    body = match.group("body").strip()
    # If the next heading was consumed, trim any trailing heading marker remnants.
    body = re.sub(r"\n##\s.*$", "", body, flags=re.DOTALL)
    return body.strip()


def parse_sections(notes_text: str) -> list[AudioSection]:
    """Parse note sections from notes.md, capturing summaries and bullet points."""
    sections: list[AudioSection] = []
    current: AudioSection | None = None
    summary_lines: list[str] = []

    for raw_line in notes_text.splitlines():
        line = raw_line.rstrip()
        heading_match = re.match(r"^(#{2,6})\s+(.*)$", line)
        if heading_match:
            heading = heading_match.group(2).strip()
            if heading in {"Contents", "Executive Summary"}:
                current = None
                summary_lines = []
                continue
            if current is not None:
                current.summary = " ".join(summary_lines).strip()
                sections.append(current)
            current = AudioSection(level=len(heading_match.group(1)), heading=heading)
            summary_lines = []
            continue

        if current is None:
            continue

        if not line or line.startswith("*") or line.startswith("<video"):
            continue
        if line.startswith("![") or line.startswith("  !["):
            continue
        if line.startswith("- "):
            current.key_points.append(line[2:].strip())
            continue
        summary_lines.append(line.strip())

    if current is not None:
        current.summary = " ".join(summary_lines).strip()
        sections.append(current)

    return sections


def extract_transcript_body(transcript_text: str) -> str:
    """Strip transcript headers and timestamps for audio output."""
    lines = []
    for line in transcript_text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cleaned = re.sub(r"^\[\d{1,2}:\d{2}(?::\d{2})?\]\s*", "", line).strip()
        if cleaned:
            lines.append(cleaned)
    return " ".join(lines)


def build_audio_text_from_saved_output(
    level: float,
    executive_summary: str,
    sections: list[AudioSection],
    transcript_body: str,
) -> str:
    """Build audio text from saved markdown/transcript content."""
    level = max(0.0, min(1.0, level))
    leaf_sections = _leaf_audio_sections(sections)

    if level >= 1.0 and transcript_body:
        return transcript_body

    if level <= 0.0:
        if executive_summary:
            return _speech_clean(executive_summary)
        return ". ".join(section.heading for section in leaf_sections) + "."

    parts: list[str] = []
    if executive_summary:
        parts.append(_speech_clean(executive_summary))

    if level >= 0.3:
        parts.append(". ".join(f"Section: {section.heading}" for section in leaf_sections))

    if level >= 0.5:
        for section in leaf_sections:
            if section.summary:
                parts.append(f"{section.heading}. {_speech_clean(section.summary)}")

    if level >= 0.7:
        for section in leaf_sections:
            if section.key_points:
                points = ". ".join(_speech_clean(point) for point in section.key_points)
                parts.append(f"{section.heading}. {points}")

    return "\n\n".join(part for part in parts if part.strip())


def _leaf_audio_sections(sections: list[AudioSection]) -> list[AudioSection]:
    """Keep only leaf sections — those with no deeper child immediately following."""
    if not sections:
        return []
    leaves = []
    for i, section in enumerate(sections):
        has_child = (
            i + 1 < len(sections) and sections[i + 1].level > section.level
        )
        if not has_child:
            leaves.append(section)
    return leaves or sections


def _speech_clean(text: str) -> str:
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"^- ", "", text, flags=re.MULTILINE)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _audio_filename(level: float) -> str:
    label = str(level).replace(".", "_")
    return f"summary_level_{label}.mp3"
