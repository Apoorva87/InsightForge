"""Output data models — the final assembled Markdown document."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from insightforge.models.frame import Frame


class NoteSection(BaseModel):
    """A single section of the final note, produced by Stage 7 (LLM processing)."""

    section_id: str                          # e.g. "section_0005"
    chunk_id: str                            # source chunk
    source_chunk_ids: list[str] = []         # source chunk ids contributing to this section
    timestamp_start: float                   # seconds
    timestamp_end: float                     # seconds
    heading: str                             # LLM-generated heading
    summary: str                             # LLM-generated summary paragraph
    key_points: list[str] = []               # bullet points
    formulas: list[str] = []                 # LaTeX/plain-text formulas (educational mode)
    code_snippets: list[str] = []            # illustrative code examples (educational mode)
    examples: list[str] = []                 # worked examples or analogies (educational mode)
    frames: list[Frame] = []                 # associated frames for inline embedding
    subsections: list["NoteSection"] = []    # optional nested sub-sections

    @property
    def timestamp_str(self) -> str:
        return self._format_time(self.timestamp_start)

    @property
    def timestamp_end_str(self) -> str:
        return self._format_time(self.timestamp_end)

    @staticmethod
    def _format_time(seconds: float) -> str:
        total = int(seconds)
        h, remainder = divmod(total, 3600)
        m, s = divmod(remainder, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @property
    def is_leaf(self) -> bool:
        return len(self.subsections) == 0

    def leaf_sections(self) -> list["NoteSection"]:
        if self.is_leaf:
            return [self]

        leaves: list[NoteSection] = []
        for subsection in self.subsections:
            leaves.extend(subsection.leaf_sections())
        return leaves


class FinalOutput(BaseModel):
    """The complete assembled output for a video job."""

    video_id: str
    title: str
    channel: str
    duration_seconds: float
    video_url: Optional[str] = None         # original YouTube URL for section links
    executive_summary: str = ""             # LLM-generated overview of the full video
    sections: list[NoteSection]
    markdown_content: str = ""          # fully rendered Markdown string
    transcript_md_content: str = ""    # rendered transcript.md with raw text + frames
    notes_path: Optional[Path] = None       # path to written notes.md
    transcript_path: Optional[Path] = None   # path to transcript.txt
    frames_dir: Optional[Path] = None        # path to frames/ directory
    clips_dir: Optional[Path] = None        # path to clips/ directory
    source_video_path: Optional[Path] = None # copied local source video for HTML viewer
    audio_path: Optional[Path] = None       # path to summary.mp3
    html_path: Optional[Path] = None        # path to HTML viewer
    notes_html_path: Optional[Path] = None  # path to notes-only HTML page
    metadata_path: Optional[Path] = None     # path to metadata.json

    @property
    def section_count(self) -> int:
        return len(self.leaf_sections)

    @property
    def leaf_sections(self) -> list[NoteSection]:
        leaves: list[NoteSection] = []
        for section in self.sections:
            leaves.extend(section.leaf_sections())
        return leaves


NoteSection.model_rebuild()
