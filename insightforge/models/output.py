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
    timestamp_start: float                   # seconds
    timestamp_end: float                     # seconds
    heading: str                             # LLM-generated heading
    summary: str                             # LLM-generated summary paragraph
    key_points: list[str] = []               # bullet points
    frames: list[Frame] = []                 # associated frames for inline embedding

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
    audio_path: Optional[Path] = None       # path to summary.mp3
    metadata_path: Optional[Path] = None     # path to metadata.json

    @property
    def section_count(self) -> int:
        return len(self.sections)
