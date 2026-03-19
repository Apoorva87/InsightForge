"""Lightweight vision utilities for frame classification, description, and reranking."""

from __future__ import annotations

import base64
import json
import mimetypes
import time
from pathlib import Path
from typing import Optional

from insightforge.utils.logging import get_logger

logger = get_logger(__name__)


class VisionReranker:
    """Classify, describe, and rank frames using a vision-language model."""

    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        model: str = "qwen/qwen3-vl-8b",
        api_key: str = "lm-studio",
        timeout: float = 45.0,
    ) -> None:
        try:
            import openai as _openai
        except ImportError as exc:
            raise ImportError(
                "openai package is required for VisionReranker. "
                "Install it with: pip install openai"
            ) from exc

        self._openai = _openai
        self._client = _openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Batch frame classification (Improvement #4)
    # ------------------------------------------------------------------

    def classify_frames(
        self,
        frames: list[tuple[str, Path]],
        batch_size: int = 8,
    ) -> dict[str, dict]:
        """Classify frames by type and educational value in batches.

        Returns a dict keyed by frame_id with:
            {"frame_type": str, "content_score": float, "description": str}
        """
        results: dict[str, dict] = {}
        for i in range(0, len(frames), batch_size):
            batch = frames[i : i + batch_size]
            batch_results = self._classify_batch(batch)
            results.update(batch_results)
        return results

    def _classify_batch(self, frames: list[tuple[str, Path]]) -> dict[str, dict]:
        """Classify a single batch of frames."""
        if not frames:
            return {}

        ids = ", ".join(fid for fid, _ in frames)
        prompt = (
            "Classify each video screenshot. For each frame, determine:\n"
            "1. frame_type: one of slide, diagram, code, equation, chart, table, "
            "whiteboard, talking_head, transition, other\n"
            "2. content_score: 0.0 (no educational value, e.g. pure talking head or blur) "
            "to 1.0 (rich educational content like detailed diagram, code, or annotated slide)\n"
            "3. description: one sentence describing what is visually shown\n\n"
            f"Frame ids: {ids}\n\n"
            "Return ONLY valid JSON in this format:\n"
            '{"frames": [{"id": "frame_id", "frame_type": "slide", '
            '"content_score": 0.85, "description": "A slide showing..."}]}'
        )

        content: list[dict] = [{"type": "text", "text": prompt}]
        for frame_id, path in frames:
            content.append({"type": "text", "text": f"Frame {frame_id}"})
            content.append(
                {"type": "image_url", "image_url": {"url": _image_as_data_url(path)}}
            )

        start = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                max_tokens=150 * len(frames),
                temperature=0.0,
                timeout=self.timeout,
            )
        except self._openai.OpenAIError as exc:
            logger.warning("Frame classification failed: %s", exc)
            return {}

        elapsed_ms = (time.monotonic() - start) * 1000
        text = response.choices[0].message.content or ""
        logger.debug("Frame classification completed in %.0fms for %d frames", elapsed_ms, len(frames))

        return _parse_classification_response(text, valid_ids={fid for fid, _ in frames})

    # ------------------------------------------------------------------
    # Per-section reranking with descriptions (Improvements #5 + existing)
    # ------------------------------------------------------------------

    def rank_frames(
        self,
        section_heading: str,
        section_summary: str,
        key_points: list[str],
        candidates: list[tuple[str, Path]],
        keep: int = 2,
        educational: bool = False,
    ) -> list[dict]:
        """Return candidate info ordered best-first for explanatory value.

        Returns list of dicts with keys: id, description (when VLM provides one).
        Falls back to list of plain id strings for backward compat if parsing fails.
        """
        if not candidates:
            return []

        prompt = self._build_rerank_prompt(
            section_heading, section_summary, key_points,
            [cid for cid, _ in candidates], keep, educational=educational,
        )
        content: list[dict] = [{"type": "text", "text": prompt}]
        for candidate_id, path in candidates:
            content.append({"type": "text", "text": f"Candidate {candidate_id}"})
            content.append(
                {"type": "image_url", "image_url": {"url": _image_as_data_url(path)}}
            )

        start = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                max_tokens=300,
                temperature=0.0,
                timeout=self.timeout,
            )
        except self._openai.OpenAIError as exc:
            raise VisionRerankerError(f"Vision ranking failed: {exc}") from exc

        elapsed_ms = (time.monotonic() - start) * 1000
        text = response.choices[0].message.content or ""
        logger.debug(
            "Vision reranking completed in %.0fms for %d candidates",
            elapsed_ms, len(candidates),
        )

        valid = {cid for cid, _ in candidates}
        result = _parse_rerank_response(text, valid)
        if result:
            return result

        # Fallback: try old-style ranked_ids parsing
        ids = _parse_ranked_ids(text, valid)
        return [{"id": i} for i in ids] if ids else []

    @staticmethod
    def _build_rerank_prompt(
        section_heading: str,
        section_summary: str,
        key_points: list[str],
        candidate_ids: list[str],
        keep: int,
        educational: bool = False,
    ) -> str:
        points = "\n".join(f"- {point}" for point in key_points[:4]) or "- none"
        ids = ", ".join(candidate_ids)
        if educational:
            instruction = (
                "You are ranking screenshot candidates for educational study notes.\n"
                "STRONGLY prefer frames showing diagrams, flowcharts, equations, code, slides, "
                "tables, charts, whiteboards, or any visual teaching aid — even if partially visible.\n"
                "Only penalize frames that are PURELY a talking head with NO educational content visible.\n"
                "Penalize blurry transitions and near-duplicates.\n"
            )
        else:
            instruction = (
                "You are ranking screenshot candidates for study notes.\n"
                "Choose the frames that best explain the section, preferring readable diagrams, "
                "equations, code, labels, or slides.\n"
                "Penalize talking heads, blurry transitions, and near-duplicates.\n"
            )
        return (
            f"{instruction}\n"
            f"Section heading: {section_heading}\n"
            f"Section summary: {section_summary}\n"
            f"Key points:\n{points}\n\n"
            f"Candidate ids: {ids}\n"
            f"Return ONLY valid JSON in this format:\n"
            f'{{"ranked": [{{"id": "best_id", "description": "one sentence describing what this frame shows"}}, '
            f'{{"id": "next_id", "description": "..."}}], "reason": "short explanation"}}\n'
            f"where ranked contains up to {keep} entries from the candidate list in best-first order. "
            f"Each description should say what is VISUALLY shown in the frame (not what the speaker is saying)."
        )

    # Keep old _build_prompt for backward compatibility in tests
    _build_prompt = _build_rerank_prompt


class VisionRerankerError(Exception):
    """Raised when the vision reranker fails."""


def _image_as_data_url(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type:
        mime_type = "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _parse_ranked_ids(text: str, valid_ids: set[str]) -> list[str]:
    """Parse old-style ranked_ids response."""
    text = text.strip()
    try:
        payload = json.loads(text)
        ranked_ids = payload.get("ranked_ids", [])
        return [candidate_id for candidate_id in ranked_ids if candidate_id in valid_ids]
    except Exception:
        pass

    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        payload = json.loads(text[start:end])
        ranked_ids = payload.get("ranked_ids", [])
        return [candidate_id for candidate_id in ranked_ids if candidate_id in valid_ids]
    except Exception:
        return []


def _parse_rerank_response(text: str, valid_ids: set[str]) -> list[dict]:
    """Parse new-style rerank response with descriptions."""
    text = text.strip()
    payload = _try_parse_json(text)
    if not payload:
        return []

    ranked = payload.get("ranked", [])
    if not isinstance(ranked, list):
        return []

    results = []
    for entry in ranked:
        if isinstance(entry, dict) and entry.get("id") in valid_ids:
            results.append({
                "id": entry["id"],
                "description": entry.get("description", ""),
            })
    return results


def _parse_classification_response(text: str, valid_ids: set[str]) -> dict[str, dict]:
    """Parse batch classification response."""
    text = text.strip()
    payload = _try_parse_json(text)
    if not payload:
        return {}

    frames_list = payload.get("frames", [])
    if not isinstance(frames_list, list):
        return {}

    results: dict[str, dict] = {}
    for entry in frames_list:
        if not isinstance(entry, dict):
            continue
        frame_id = entry.get("id", "")
        if frame_id not in valid_ids:
            continue
        results[frame_id] = {
            "frame_type": entry.get("frame_type", "other"),
            "content_score": max(0.0, min(1.0, float(entry.get("content_score", 0.5)))),
            "description": entry.get("description", ""),
        }
    return results


def _try_parse_json(text: str) -> Optional[dict]:
    """Try to parse JSON from text, handling markdown fences and surrounding prose."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = text.strip()

    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
