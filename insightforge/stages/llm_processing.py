"""Stage 7 — LLM Processing: generate structured notes for each scored chunk."""

from __future__ import annotations

import json
import re
from typing import Optional

from insightforge.llm.base import LLMProvider, LLMRequest
from insightforge.models.frame import FrameSet
from insightforge.models.output import NoteSection
from insightforge.models.scoring import ScoredChunk
from insightforge.utils.logging import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a precise note-taking assistant. Given a transcript chunk from a YouTube video, "
    "produce a structured JSON note section. "
    "Respond ONLY with valid JSON — no markdown fences, no extra text."
)

_EXEC_SUMMARY_SYSTEM = (
    "You are a note-taking assistant. Write a concise executive summary."
)

_EXEC_SUMMARY_TEMPLATE = """\
Below are section summaries from a video titled "{title}" by {channel}.

{section_summaries}

Write an executive summary (2-4 sentences) covering the video's main thesis and key takeaways. \
Then list 3-5 key highlights as bullet points.

Respond ONLY with valid JSON:
{{"executive_summary": "...", "highlights": ["...", "..."]}}"""

_USER_TEMPLATE = """\
Timestamp: {timestamp}
Transcript chunk:
{text}

Produce a JSON object with these exact keys:
- "heading": concise section heading (max 8 words)
- "summary": 1-3 sentence summary paragraph
- "key_points": list of 2-5 bullet point strings

JSON only:"""

# Default token budget — high enough for reasoning models to think + produce output.
DEFAULT_MAX_TOKENS = 8192


def run(
    scored_chunks: list[ScoredChunk],
    llm: LLMProvider,
    frame_set: Optional[FrameSet] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[NoteSection]:
    """Generate a NoteSection for each important chunk.

    Args:
        scored_chunks: Filtered ScoredChunks from Stage 6.
        llm: LLM provider for note generation.
        frame_set: Optional FrameSet to attach relevant frames to sections.
        max_tokens: Token budget for LLM requests.

    Returns:
        Ordered list of NoteSection objects.
    """
    sections: list[NoteSection] = []

    for i, sc in enumerate(scored_chunks):
        logger.debug(
            "Processing chunk %s (score=%.2f)", sc.chunk.chunk_id, sc.composite_score
        )
        section = _generate_section(i, sc, llm, frame_set, max_tokens)
        sections.append(section)

    logger.info("LLM processing: generated %d note sections", len(sections))
    return sections


def generate_executive_summary(
    sections: list[NoteSection],
    llm: LLMProvider,
    title: str,
    channel: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """Generate an executive summary from all section summaries."""
    summaries = "\n".join(
        f"- [{s.timestamp_str}] {s.heading}: {s.summary}" for s in sections
    )
    prompt = _EXEC_SUMMARY_TEMPLATE.format(
        title=title, channel=channel, section_summaries=summaries
    )
    request = LLMRequest(
        prompt=prompt,
        system=_EXEC_SUMMARY_SYSTEM,
        max_tokens=max_tokens,
        temperature=0.2,
    )
    try:
        response = llm.complete(request)
        text = response.text.strip()
        if not text:
            return _fallback_executive_summary(sections)
        data = _parse_json_response(text)
        parts = []
        if data.get("executive_summary"):
            parts.append(data["executive_summary"])
        if data.get("highlights"):
            parts.append("")
            parts.append("**Key highlights:**")
            for h in data["highlights"]:
                parts.append(f"- {h}")
        return "\n".join(parts) if parts else _fallback_executive_summary(sections)
    except Exception as exc:
        logger.warning("Executive summary generation failed: %s; using fallback", exc)
        return _fallback_executive_summary(sections)


def _fallback_executive_summary(sections: list[NoteSection]) -> str:
    """Build a simple executive summary from section headings and summaries."""
    parts = [f"This video covers {len(sections)} topics:"]
    for s in sections:
        parts.append(f"- **{s.heading}** ({s.timestamp_str}): {s.summary[:120]}")
    return "\n".join(parts)


def _generate_section(
    index: int,
    sc: ScoredChunk,
    llm: LLMProvider,
    frame_set: Optional[FrameSet],
    max_tokens: int,
) -> NoteSection:
    """Generate a single NoteSection from a ScoredChunk."""
    # Send full chunk text (up to 4K chars) to give LLM maximum context
    prompt = _USER_TEMPLATE.format(
        timestamp=sc.chunk.timestamp_str,
        text=sc.chunk.text[:4000],
    )
    request = LLMRequest(
        prompt=prompt,
        system=_SYSTEM_PROMPT,
        max_tokens=max_tokens,
        temperature=0.2,
    )

    try:
        response = llm.complete(request)
        text = response.text.strip()
        if not text:
            logger.warning("LLM returned empty for %s; using fallback", sc.chunk.chunk_id)
            data = _fallback_section_data(sc)
        else:
            data = _parse_json_response(text)
    except Exception as exc:
        logger.warning("LLM generation failed for %s: %s; using fallback", sc.chunk.chunk_id, exc)
        data = _fallback_section_data(sc)

    # Attach ALL frames within the section's time range, not just the nearest one.
    # This captures code screenshots, diagrams, and visual transitions.
    frames = []
    if frame_set:
        frames = frame_set.get_frames_in_range(sc.chunk.start, sc.chunk.end)
        # If no frames in range, fall back to nearest within 30s
        if not frames:
            nearest = frame_set.get_frame_near(sc.chunk.midpoint, tolerance=30.0)
            if nearest:
                frames = [nearest]

    return NoteSection(
        section_id=f"section_{index:04d}",
        chunk_id=sc.chunk.chunk_id,
        timestamp_start=sc.chunk.start,
        timestamp_end=sc.chunk.end,
        heading=data.get("heading", f"Section {index + 1}"),
        summary=data.get("summary", ""),
        key_points=data.get("key_points", []),
        frames=frames,
    )


def _parse_json_response(text: str) -> dict:
    """Parse LLM response as JSON, stripping markdown fences and surrounding prose."""
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    # Try direct parse
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # Try to find a JSON object with expected keys in the text
    match = re.search(r'\{[^{}]*"heading"[^{}]*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    # Find any JSON object
    match = re.search(r'\{[^{}]+\}', text)
    if match:
        return json.loads(match.group(0))
    raise json.JSONDecodeError("No JSON object found", text, 0)


def _fallback_section_data(sc: ScoredChunk) -> dict:
    """Generate a readable section dict when LLM fails.

    Instead of dumping raw transcript text, extract the first few
    sentences and use them as structured summary + bullet points.
    """
    text = sc.chunk.text.strip()
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    if not sentences:
        sentences = [text[:300]]

    summary = ". ".join(sentences[:2])
    if not summary.endswith("."):
        summary += "."

    # Use sentences 2–5 as key points (skip the first which is in the summary)
    key_points = sentences[1:5] if len(sentences) > 1 else []

    return {
        "heading": f"Section at {sc.chunk.timestamp_str}",
        "summary": summary[:500],
        "key_points": key_points,
    }
