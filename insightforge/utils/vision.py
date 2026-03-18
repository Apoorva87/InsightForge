"""Lightweight vision utilities for section-aware frame reranking."""

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
    """Rank a small set of candidate frames for one note section."""

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

    def rank_frames(
        self,
        section_heading: str,
        section_summary: str,
        key_points: list[str],
        candidates: list[tuple[str, Path]],
        keep: int = 2,
    ) -> list[str]:
        """Return candidate ids ordered best-first for explanatory value."""
        if not candidates:
            return []

        prompt = self._build_prompt(section_heading, section_summary, key_points, [cid for cid, _ in candidates], keep)
        content = [{"type": "text", "text": prompt}]
        for candidate_id, path in candidates:
            content.append({"type": "text", "text": f"Candidate {candidate_id}"})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": _image_as_data_url(path),
                    },
                }
            )

        start = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                max_tokens=200,
                temperature=0.0,
                timeout=self.timeout,
            )
        except self._openai.OpenAIError as exc:
            raise VisionRerankerError(f"Vision ranking failed: {exc}") from exc

        elapsed_ms = (time.monotonic() - start) * 1000
        text = response.choices[0].message.content or ""
        ids = _parse_ranked_ids(text, valid_ids={cid for cid, _ in candidates})
        logger.debug(
            "Vision reranking completed in %.0fms for %d candidates",
            elapsed_ms,
            len(candidates),
        )
        return ids

    @staticmethod
    def _build_prompt(
        section_heading: str,
        section_summary: str,
        key_points: list[str],
        candidate_ids: list[str],
        keep: int,
    ) -> str:
        points = "\n".join(f"- {point}" for point in key_points[:4]) or "- none"
        ids = ", ".join(candidate_ids)
        return (
            "You are ranking screenshot candidates for study notes.\n"
            "Choose the frames that best explain the section, preferring readable diagrams, equations, code, labels, or slides.\n"
            "Penalize talking heads, blurry transitions, and near-duplicates.\n\n"
            f"Section heading: {section_heading}\n"
            f"Section summary: {section_summary}\n"
            f"Key points:\n{points}\n\n"
            f"Candidate ids: {ids}\n"
            f"Return ONLY valid JSON in this format: "
            f'{{"ranked_ids": ["best", "next"], "reason": "short"}} '
            f"where ranked_ids contains up to {keep} ids from the candidate list in best-first order."
        )


class VisionRerankerError(Exception):
    """Raised when the vision reranker fails."""


def _image_as_data_url(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type:
        mime_type = "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _parse_ranked_ids(text: str, valid_ids: set[str]) -> list[str]:
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
