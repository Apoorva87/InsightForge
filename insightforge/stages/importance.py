"""Stage 6 — Importance Scoring: score chunks by semantic importance."""

from __future__ import annotations

import json
from typing import Optional

from insightforge.llm.base import LLMProvider, LLMRequest
from insightforge.models.chunk import Chunk, ChunkBatch
from insightforge.models.frame import FrameSet
from insightforge.models.scoring import ScoredChunk
from insightforge.utils.logging import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You rate transcript chunks. Reply with ONLY a number between 0.0 and 1.0. "
    "Nothing else — just the number."
)

_USER_TEMPLATE = (
    "Rate this transcript chunk from 0.0 (filler/intro) to 1.0 (core educational content).\n\n"
    "{text}\n\n"
    "Score:"
)


def run(
    chunk_batch: ChunkBatch,
    llm: LLMProvider,
    frame_set: Optional[FrameSet] = None,
    threshold: float = 0.4,
    llm_weight: float = 0.7,
    visual_weight: float = 0.3,
    batch_size: int = 5,
) -> list[ScoredChunk]:
    """Score all chunks by importance using LLM + optional visual signal.

    Args:
        chunk_batch: ChunkBatch from Stage 4.
        llm: LLM provider for scoring.
        frame_set: Optional FrameSet for visual scene-change signal (Stage 5).
        threshold: Minimum composite score to consider important.
        llm_weight: Weight of LLM score in composite.
        visual_weight: Weight of visual score in composite.
        batch_size: Number of chunks per LLM batch (future: batch prompting).

    Returns:
        List of ScoredChunk objects for all chunks.
    """
    visual_scores = _compute_visual_scores(chunk_batch, frame_set)

    scored: list[ScoredChunk] = []
    for chunk in chunk_batch.chunks:
        llm_score = _score_chunk_llm(chunk, llm)
        vis_score = visual_scores.get(chunk.chunk_id, 0.0)

        sc = ScoredChunk(
            chunk=chunk,
            llm_score=llm_score,
            visual_score=vis_score,
        )
        sc.compute_composite(llm_weight=llm_weight, visual_weight=visual_weight)
        scored.append(sc)

    above = sum(1 for s in scored if s.composite_score >= threshold)
    logger.info(
        "Importance scoring: %d/%d chunks above threshold %.2f",
        above,
        len(scored),
        threshold,
    )
    return scored


def passthrough(chunk_batch: ChunkBatch) -> list[ScoredChunk]:
    """Create ScoredChunks with default scores, skipping LLM calls.

    Used when detail=high to avoid unnecessary LLM calls since all chunks
    are retained regardless of score.
    """
    scored = []
    for chunk in chunk_batch.chunks:
        sc = ScoredChunk(
            chunk=chunk,
            llm_score=0.5,
            visual_score=0.0,
        )
        sc.compute_composite(llm_weight=1.0, visual_weight=0.0)
        scored.append(sc)
    logger.info("Importance passthrough: %d chunks (LLM scoring skipped)", len(scored))
    return scored


def apply_visual_scores(
    scored_chunks: list[ScoredChunk],
    frame_set: Optional[FrameSet],
    llm_weight: float = 0.7,
    visual_weight: float = 0.3,
) -> list[ScoredChunk]:
    """Apply visual scores to existing scored chunks and recompute composite scores.

    This lets the pipeline preserve concurrency: LLM scoring can run while frames
    are extracted, then the visual signal can be merged in after both branches join.
    """
    if frame_set is None or not frame_set.frames:
        return scored_chunks

    chunk_batch = ChunkBatch(chunks=[sc.chunk for sc in scored_chunks], strategy="scored")
    visual_scores = _compute_visual_scores(chunk_batch, frame_set)

    for sc in scored_chunks:
        sc.visual_score = visual_scores.get(sc.chunk.chunk_id, 0.0)
        sc.compute_composite(llm_weight=llm_weight, visual_weight=visual_weight)

    return scored_chunks


def _score_chunk_llm(chunk: Chunk, llm: LLMProvider) -> float:
    """Ask the LLM for an importance score for a single chunk."""
    prompt = _USER_TEMPLATE.format(timestamp=chunk.timestamp_str, text=chunk.text[:800])
    # 512 tokens: forces thinking models to conclude quickly and produce an output.
    # Higher budgets cause some models (e.g. GLM-4-flash) to over-think and leave
    # the response field empty.
    request = LLMRequest(
        prompt=prompt,
        system=_SYSTEM_PROMPT,
        max_tokens=512,
        temperature=0.0,
    )
    try:
        response = llm.complete(request)
        text = response.text.strip()
        if not text:
            logger.warning("LLM returned empty response for %s; defaulting to 0.5", chunk.chunk_id)
            return 0.5
        return _parse_score(text)
    except Exception as exc:
        logger.warning("LLM scoring failed for %s: %s; defaulting to 0.5", chunk.chunk_id, exc)
        return 0.5


def _parse_score(text: str) -> float:
    """Parse a score from LLM response text.

    Handles:
    - Bare float: 0.8
    - JSON: {"score": 0.8}
    - Verbose assessment with embedded numbers
    - Score patterns: "Score: 0.8", "importance: 0.75"
    - 0-10 scale normalisation
    """
    import re

    text = text.strip().strip("'\"")

    # Try direct float parse first
    try:
        return max(0.0, min(1.0, float(text)))
    except ValueError:
        pass

    # Try JSON
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "score" in data:
            return max(0.0, min(1.0, float(data["score"])))
    except (json.JSONDecodeError, ValueError):
        pass

    # Look for score-like patterns: "score: 0.8", "Score = 0.75", "importance: 0.6"
    score_match = re.search(
        r"(?:score|importance|rating|value)[:\s=]+([0-9]+\.?[0-9]*)", text, re.IGNORECASE
    )
    if score_match:
        val = float(score_match.group(1))
        if val > 1.0:
            val = val / 10.0
        return max(0.0, min(1.0, val))

    # Find ALL floats in text, prefer 0.x range values
    all_floats = re.findall(r"\b(0\.[0-9]+|1\.0|[0-9]+\.?[0-9]*)\b", text)
    for f_str in all_floats:
        val = float(f_str)
        if 0.0 <= val <= 1.0:
            return val
    # If only out-of-range numbers found, normalise the first one
    if all_floats:
        val = float(all_floats[0])
        if val > 1.0:
            val = val / 10.0
        return max(0.0, min(1.0, val))

    # Last resort: default to 0.5 instead of raising
    logger.warning("Could not parse score from: %.100s; defaulting to 0.5", text)
    return 0.5


def _compute_visual_scores(
    chunk_batch: ChunkBatch,
    frame_set: Optional[FrameSet],
) -> dict[str, float]:
    """Map chunk_id → visual score derived from nearest frame's scene diff.

    Returns a dict with scores in [0.0, 1.0]. Chunks without a nearby frame get 0.0.
    """
    if frame_set is None or not frame_set.frames:
        return {}

    scores: dict[str, float] = {}
    for chunk in chunk_batch.chunks:
        frame = frame_set.get_frame_near(chunk.midpoint, tolerance=15.0)
        if not frame:
            continue

        visual_score = frame.scene_diff_score
        if visual_score is None:
            visual_score = frame.content_score

        if visual_score is not None:
            scores[chunk.chunk_id] = max(0.0, min(1.0, visual_score))
    return scores


def filter_by_detail(
    scored_chunks: list[ScoredChunk],
    detail: str,
    threshold: float = 0.4,
) -> list[ScoredChunk]:
    """Filter chunks based on --detail mode.

    Args:
        scored_chunks: All scored chunks from run().
        detail: "high" keeps ALL chunks (scores used for ordering only);
                "low" keeps top quartile by score.
        threshold: Minimum composite score (used in low mode only).

    Returns:
        Filtered list of ScoredChunk.
    """
    if detail == "low":
        above_threshold = [s for s in scored_chunks if s.composite_score >= threshold]
        if not above_threshold:
            above_threshold = scored_chunks  # never return empty
        sorted_chunks = sorted(above_threshold, key=lambda s: s.composite_score, reverse=True)
        top_n = max(1, len(sorted_chunks) // 4)
        selected = sorted_chunks[:top_n]
        return sorted(selected, key=lambda s: (s.chunk.start, s.chunk.end))

    # detail=high: keep ALL chunks — the whole video is worth summarising
    return scored_chunks
