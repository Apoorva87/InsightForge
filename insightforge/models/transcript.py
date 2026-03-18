"""Transcript data models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, model_validator


class TranscriptSegment(BaseModel):
    """A single timestamped segment of transcript text."""

    start: float        # seconds
    end: float          # seconds
    text: str
    confidence: Optional[float] = None   # 0.0–1.0, from Whisper

    @model_validator(mode="after")
    def end_after_start(self) -> "TranscriptSegment":
        if self.end < self.start:
            raise ValueError(f"end ({self.end}) must be >= start ({self.start})")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def timestamp_str(self) -> str:
        """Return start time as MM:SS or HH:MM:SS."""
        total = int(self.start)
        h, remainder = divmod(total, 3600)
        m, s = divmod(remainder, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"


class TranscriptResult(BaseModel):
    """Full transcript produced by Stage 2, refined by Stage 3."""

    segments: list[TranscriptSegment]
    source: str = "whisper"          # "whisper" | "youtube_manual" | "youtube_auto"
    language: Optional[str] = None   # detected language code, e.g. "en"
    word_count: int = 0
    is_aligned: bool = False         # True after Stage 3 alignment

    @model_validator(mode="after")
    def compute_word_count(self) -> "TranscriptResult":
        if self.word_count == 0 and self.segments:
            self.word_count = sum(len(seg.text.split()) for seg in self.segments)
        return self

    @property
    def full_text(self) -> str:
        return " ".join(seg.text for seg in self.segments)

    @property
    def duration_seconds(self) -> float:
        if not self.segments:
            return 0.0
        return self.segments[-1].end
