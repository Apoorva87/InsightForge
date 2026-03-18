"""Importance scoring data models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, field_validator

from insightforge.models.chunk import Chunk


class ScoredChunk(BaseModel):
    """A chunk annotated with composite importance score."""

    chunk: Chunk
    llm_score: float = 0.0           # 0.0–1.0 from LLM importance judgment
    visual_score: float = 0.0        # 0.0–1.0 from frame scene-diff signal
    composite_score: float = 0.0     # weighted combination

    @field_validator("llm_score", "visual_score", "composite_score")
    @classmethod
    def score_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"Score must be in [0.0, 1.0], got {v}")
        return v

    def compute_composite(self, llm_weight: float = 0.7, visual_weight: float = 0.3) -> None:
        """Recompute composite_score from component scores and weights."""
        self.composite_score = (
            self.llm_score * llm_weight + self.visual_score * visual_weight
        )

    @property
    def is_important(self) -> bool:
        """True when composite score exceeds default threshold."""
        return self.composite_score >= 0.4
