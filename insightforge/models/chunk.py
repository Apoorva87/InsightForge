"""Chunking data models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, model_validator


class Chunk(BaseModel):
    """A token-bounded, semantically coherent chunk of transcript."""

    chunk_id: str                        # e.g. "chunk_0042"
    text: str
    start: float                         # seconds — earliest segment start
    end: float                           # seconds — latest segment end
    token_count: int = 0
    segment_indices: list[int] = []      # indices into TranscriptResult.segments

    @model_validator(mode="after")
    def validate_bounds(self) -> "Chunk":
        if self.end < self.start:
            raise ValueError(f"Chunk end ({self.end}) must be >= start ({self.start})")
        return self

    @property
    def midpoint(self) -> float:
        return (self.start + self.end) / 2

    @property
    def timestamp_str(self) -> str:
        total = int(self.start)
        h, remainder = divmod(total, 3600)
        m, s = divmod(remainder, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"


class ChunkBatch(BaseModel):
    """All chunks produced by the chunking stage."""

    chunks: list[Chunk]
    strategy: str = "hybrid"
    total_tokens: int = 0

    @model_validator(mode="after")
    def compute_total_tokens(self) -> "ChunkBatch":
        if self.total_tokens == 0 and self.chunks:
            self.total_tokens = sum(c.token_count for c in self.chunks)
        return self

    def __len__(self) -> int:
        return len(self.chunks)
