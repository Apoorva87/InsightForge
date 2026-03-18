"""Stage 7 — LLM Processing: hierarchical note generation from transcript chunks."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from pydantic import BaseModel

from insightforge.llm.base import LLMProvider, LLMRequest
from insightforge.models.frame import Frame, FrameSet
from insightforge.models.output import NoteSection
from insightforge.models.scoring import ScoredChunk
from insightforge.utils.logging import get_logger
from insightforge.utils.vision import VisionReranker, VisionRerankerError

logger = get_logger(__name__)

_SECTION_SYSTEM_PROMPT = (
    "You are a precise note-taking assistant. "
    "Produce concise, high-signal study notes. "
    "Respond ONLY with valid JSON."
)

_EXEC_SUMMARY_SYSTEM = (
    "You are a note-taking assistant. Write a concise executive summary."
)

_CHUNK_SUMMARY_TEMPLATE = """\
Timestamp: {timestamp}
Transcript chunk:
{text}

Writing style:
{style_guidance}

Produce a compact JSON object with these exact keys:
- "heading": concise heading (max 8 words)
- "main_idea": 1-2 sentence summary of the chunk
- "key_points": list of 2-4 bullet point strings
- "keywords": list of 3-8 short keywords or phrases
- "transition": one of "continue", "shift", "conclusion"

JSON only:"""

_TOPIC_SECTION_TEMPLATE = """\
You are given compressed chunk summaries from one contiguous topic in a video.
Synthesize them into a reader-friendly note section.

Topic span: {timestamp}

Writing style:
{style_guidance}

Coherence guidance:
{coherence_guidance}

Chunk summaries:
{outline}

Produce a JSON object with these exact keys:
- "heading": concise section heading (max 8 words)
- "summary": 1-3 sentence summary paragraph
- "key_points": list of 2-5 bullet point strings

JSON only:"""

_PARENT_TOPIC_TEMPLATE = """\
You are given summaries of sub-sections that belong to one larger topic in a video.
Write a parent topic overview that introduces the topic without repeating the sub-sections verbatim.

Topic span: {timestamp}

Writing style:
{style_guidance}

Coherence guidance:
{coherence_guidance}

Sub-section summaries:
{outline}

Produce a JSON object with these exact keys:
- "heading": concise topic heading (max 8 words)
- "summary": 1-3 sentence summary paragraph
- "key_points": list of 2-5 bullet point strings

JSON only:"""

_EXEC_SUMMARY_TEMPLATE = """\
Below are section summaries from a video titled "{title}" by {channel}.

{section_summaries}

Write an executive summary (2-4 sentences) covering the video's main thesis and key takeaways. \
Then list 3-5 key highlights as bullet points.

Respond ONLY with valid JSON:
{{"executive_summary": "...", "highlights": ["...", "..."]}}"""

DEFAULT_MAX_TOKENS = 8192
DEFAULT_PARALLEL_WORKERS = 4
DEFAULT_EXPLANATION_STYLE = "well_explained"
DEFAULT_COHERENCE_GUIDANCE = (
    "Situate this section within the broader flow of the video. Open with enough context that a reader "
    "understands why this section matters, and end in a way that leads naturally into what follows. "
    "Keep the explanation coherent, cumulative, and educational rather than fragmentary."
)

_TRANSITION_PATTERNS = (
    r"\bnext\b",
    r"\bnow\b",
    r"\bmoving on\b",
    r"\blet'?s turn to\b",
    r"\bon the other hand\b",
    r"\bin summary\b",
    r"\bto recap\b",
    r"\bfinally\b",
)
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "that", "this", "these",
    "those", "to", "of", "for", "in", "on", "at", "by", "with", "from", "as", "is", "are",
    "was", "were", "be", "been", "being", "it", "its", "we", "you", "they", "he", "she",
    "i", "me", "my", "our", "their", "your", "about", "into", "over", "after", "before",
    "so", "because", "there", "here", "today", "will", "can", "could", "should", "would",
}

_LMSTUDIO_NO_THINKING = {
    "chat_template_kwargs": {
        "enable_thinking": False,
    }
}

_SECTION_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "note_section",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "heading": {"type": "string"},
                "summary": {"type": "string"},
                "key_points": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["heading", "summary", "key_points"],
        },
    },
}

_CHUNK_SUMMARY_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "chunk_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "heading": {"type": "string"},
                "main_idea": {"type": "string"},
                "key_points": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "transition": {
                    "type": "string",
                    "enum": ["continue", "shift", "conclusion"],
                },
            },
            "required": ["heading", "main_idea", "key_points", "keywords", "transition"],
        },
    },
}

_EXEC_SUMMARY_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "executive_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "executive_summary": {"type": "string"},
                "highlights": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["executive_summary", "highlights"],
        },
    },
}


class ChunkSummary(BaseModel):
    chunk_id: str
    start: float
    end: float
    heading: str
    main_idea: str
    key_points: list[str]
    keywords: list[str] = []
    transition: str = "continue"

    @property
    def compact_text(self) -> str:
        key_points = "; ".join(self.key_points[:4])
        keywords = ", ".join(self.keywords[:8])
        return (
            f"[{_format_time(self.start)}-{_format_time(self.end)}] {self.heading}: "
            f"{self.main_idea} | Points: {key_points} | Keywords: {keywords} | "
            f"Transition: {self.transition}"
        )


class TopicSpan(BaseModel):
    topic_id: str
    items: list[tuple[ScoredChunk, ChunkSummary]]
    start: float
    end: float
    boundary_strength: float = 0.0

    @property
    def chunk_ids(self) -> list[str]:
        return [sc.chunk.chunk_id for sc, _ in self.items]

    @property
    def summaries(self) -> list[ChunkSummary]:
        return [summary for _, summary in self.items]

    @property
    def scored_chunks(self) -> list[ScoredChunk]:
        return [sc for sc, _ in self.items]


def run(
    scored_chunks: list[ScoredChunk],
    llm: LLMProvider,
    frame_set: Optional[FrameSet] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    hierarchical: bool = True,
    chunk_summary_max_tokens: int = 1024,
    topic_summary_max_tokens: int = 2048,
    max_chunks_per_topic: int = 4,
    max_chunk_summaries_per_subsection: int = 3,
    boundary_threshold: float = 0.58,
    explanation_style: str = DEFAULT_EXPLANATION_STYLE,
    frame_rerank_enabled: bool = True,
    frame_rerank_base_url: str = "http://localhost:1234/v1",
    frame_rerank_model: str = "qwen/qwen3-vl-8b",
    frame_rerank_keep: int = 2,
    frame_rerank_max_candidates: int = 4,
    parallel_workers: int = DEFAULT_PARALLEL_WORKERS,
) -> list[NoteSection]:
    """Generate NoteSections using a hierarchical synthesis pipeline.

    Raw transcript is only used at the chunk-summary level. Topic-level synthesis
    uses compact chunk summaries so local models stay inside reliable context sizes.
    """
    vision_reranker = _build_vision_reranker(
        enabled=frame_rerank_enabled,
        base_url=frame_rerank_base_url,
        model=frame_rerank_model,
    )

    if not scored_chunks:
        return []

    if not hierarchical or len(scored_chunks) == 1:
        sections = _parallel_map(
            items=list(enumerate(scored_chunks)),
            fn=lambda item: _generate_leaf_section(
                index=item[0],
                sc=item[1],
                llm=llm,
                frame_set=frame_set,
                max_tokens=max_tokens,
                explanation_style=explanation_style,
                coherence_guidance=_coherence_context_for_chunk(scored_chunks, item[0]),
                vision_reranker=vision_reranker,
                frame_rerank_keep=frame_rerank_keep,
                frame_rerank_max_candidates=frame_rerank_max_candidates,
            ),
            max_workers=parallel_workers,
        )
        logger.info("LLM processing: generated %d sections (flat mode)", len(sections))
        return sections

    chunk_summaries = _parallel_map(
        items=scored_chunks,
        fn=lambda sc: _generate_chunk_summary(sc, llm, chunk_summary_max_tokens, explanation_style),
        max_workers=parallel_workers,
    )

    topics = _group_topics(
        scored_chunks=scored_chunks,
        chunk_summaries=chunk_summaries,
        frame_set=frame_set,
        max_chunks_per_topic=max_chunks_per_topic,
        boundary_threshold=boundary_threshold,
    )

    sections = _parallel_map(
        items=list(enumerate(topics)),
        fn=lambda item: _generate_topic_section(
            topic_index=item[0],
            topic=item[1],
            llm=llm,
            frame_set=frame_set,
            max_tokens=min(max_tokens, topic_summary_max_tokens),
            max_chunk_summaries_per_subsection=max_chunk_summaries_per_subsection,
            explanation_style=explanation_style,
            coherence_guidance=_coherence_context_for_topic(topics, item[0]),
            vision_reranker=vision_reranker,
            frame_rerank_keep=frame_rerank_keep,
            frame_rerank_max_candidates=frame_rerank_max_candidates,
        ),
        max_workers=min(parallel_workers, 4),
    )

    logger.info(
        "LLM processing: generated %d top-level sections from %d chunk summaries",
        len(sections),
        len(chunk_summaries),
    )
    return sections


def generate_executive_summary(
    sections: list[NoteSection],
    llm: LLMProvider,
    title: str,
    channel: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """Generate an executive summary from leaf section summaries."""
    leaves = _leaf_sections(sections)
    summaries = "\n".join(
        f"- [{s.timestamp_str}] {s.heading}: {s.summary}" for s in leaves
    )
    prompt = _EXEC_SUMMARY_TEMPLATE.format(
        title=title, channel=channel, section_summaries=summaries
    )
    request = LLMRequest(
        prompt=prompt,
        system=_EXEC_SUMMARY_SYSTEM,
        max_tokens=max_tokens,
        temperature=0.2,
        response_format=_EXEC_SUMMARY_RESPONSE_SCHEMA,
        extra_body=_LMSTUDIO_NO_THINKING,
    )
    try:
        response = llm.complete(request)
        text = response.text.strip()
        if not text:
            return _fallback_executive_summary(leaves)
        data = _parse_json_response(text)
        if _invalid_executive_summary_data(data):
            return _fallback_executive_summary(leaves)
        parts = []
        if data.get("executive_summary"):
            parts.append(data["executive_summary"])
        if data.get("highlights"):
            parts.append("")
            parts.append("**Key highlights:**")
            for h in data["highlights"]:
                parts.append(f"- {h}")
        return "\n".join(parts) if parts else _fallback_executive_summary(leaves)
    except Exception as exc:
        logger.warning("Executive summary generation failed: %s; using fallback", exc)
        return _fallback_executive_summary(leaves)


def _fallback_executive_summary(sections: list[NoteSection]) -> str:
    parts = [f"This video covers {len(sections)} sections:"]
    for s in sections:
        parts.append(f"- **{s.heading}** ({s.timestamp_str}): {s.summary[:120]}")
    return "\n".join(parts)


def _generate_chunk_summary(
    sc: ScoredChunk,
    llm: LLMProvider,
    max_tokens: int,
    explanation_style: str,
) -> ChunkSummary:
    prompt = _CHUNK_SUMMARY_TEMPLATE.format(
        timestamp=sc.chunk.timestamp_str,
        text=sc.chunk.text[:3000],
        style_guidance=_explanation_style_guidance(explanation_style),
    )
    request = LLMRequest(
        prompt=prompt,
        system=_SECTION_SYSTEM_PROMPT,
        max_tokens=max_tokens,
        temperature=0.1,
        response_format=_CHUNK_SUMMARY_RESPONSE_SCHEMA,
        extra_body=_LMSTUDIO_NO_THINKING,
    )

    try:
        response = llm.complete(request)
        text = response.text.strip()
        if not text:
            logger.warning("LLM returned empty chunk summary for %s; using fallback", sc.chunk.chunk_id)
            data = _fallback_chunk_summary(sc)
        else:
            data = _parse_json_response(text)
            if _invalid_chunk_summary_data(data):
                raise ValueError("Chunk summary contained placeholder or empty fields")
    except Exception as exc:
        logger.warning("Chunk summary failed for %s: %s; using fallback", sc.chunk.chunk_id, exc)
        data = _fallback_chunk_summary(sc)

    return ChunkSummary(
        chunk_id=sc.chunk.chunk_id,
        start=sc.chunk.start,
        end=sc.chunk.end,
        heading=data.get("heading", f"Chunk {_format_time(sc.chunk.start)}"),
        main_idea=data.get("main_idea", data.get("summary", "")),
        key_points=data.get("key_points", []),
        keywords=data.get("keywords", []),
        transition=data.get("transition", "continue"),
    )


def _generate_topic_section(
    topic_index: int,
    topic: TopicSpan,
    llm: LLMProvider,
    frame_set: Optional[FrameSet],
    max_tokens: int,
    max_chunk_summaries_per_subsection: int,
    explanation_style: str,
    coherence_guidance: str,
    vision_reranker: Optional[VisionReranker],
    frame_rerank_keep: int,
    frame_rerank_max_candidates: int,
) -> NoteSection:
    summaries = topic.summaries

    if len(summaries) <= max_chunk_summaries_per_subsection:
        data = _synthesize_section_data(
            prompt_template=_TOPIC_SECTION_TEMPLATE,
            timestamp=f"{_format_time(topic.start)}-{_format_time(topic.end)}",
            outline="\n".join(f"- {summary.compact_text}" for summary in summaries),
            llm=llm,
            max_tokens=max_tokens,
            explanation_style=explanation_style,
            coherence_guidance=coherence_guidance,
            fallback=_fallback_topic_data(summaries),
        )
        return NoteSection(
            section_id=f"section_{topic_index:04d}",
            chunk_id=topic.chunk_ids[0],
            source_chunk_ids=topic.chunk_ids,
            timestamp_start=topic.start,
            timestamp_end=topic.end,
            heading=data.get("heading", f"Topic {_format_time(topic.start)}"),
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            frames=_section_frames(
                frame_set,
                topic.start,
                topic.end,
                heading=data.get("heading", f"Topic {_format_time(topic.start)}"),
                summary=data.get("summary", ""),
                key_points=data.get("key_points", []),
                vision_reranker=vision_reranker,
                keep=frame_rerank_keep,
                max_candidates=frame_rerank_max_candidates,
            ),
        )

    subgroup_spans = _partition_topic(topic, max_chunk_summaries_per_subsection)
    subsections: list[NoteSection] = []
    for sub_index, subgroup in enumerate(subgroup_spans):
        subgroup_data = _synthesize_section_data(
            prompt_template=_TOPIC_SECTION_TEMPLATE,
            timestamp=f"{_format_time(subgroup.start)}-{_format_time(subgroup.end)}",
            outline="\n".join(f"- {summary.compact_text}" for summary in subgroup.summaries),
            llm=llm,
            max_tokens=max_tokens,
            explanation_style=explanation_style,
            coherence_guidance=coherence_guidance,
            fallback=_fallback_topic_data(subgroup.summaries),
        )
        subsections.append(
            NoteSection(
                section_id=f"section_{topic_index:04d}_{sub_index:02d}",
                chunk_id=subgroup.chunk_ids[0],
                source_chunk_ids=subgroup.chunk_ids,
                timestamp_start=subgroup.start,
                timestamp_end=subgroup.end,
                heading=subgroup_data.get("heading", f"Part {sub_index + 1}"),
                summary=subgroup_data.get("summary", ""),
                key_points=subgroup_data.get("key_points", []),
                frames=_section_frames(
                    frame_set,
                    subgroup.start,
                    subgroup.end,
                    heading=subgroup_data.get("heading", f"Part {sub_index + 1}"),
                    summary=subgroup_data.get("summary", ""),
                    key_points=subgroup_data.get("key_points", []),
                    vision_reranker=vision_reranker,
                    keep=frame_rerank_keep,
                    max_candidates=frame_rerank_max_candidates,
                ),
            )
        )

    parent_outline = "\n".join(
        f"- [{sub.timestamp_str}-{sub.timestamp_end_str}] {sub.heading}: {sub.summary}"
        for sub in subsections
    )
    parent_data = _synthesize_section_data(
        prompt_template=_PARENT_TOPIC_TEMPLATE,
        timestamp=f"{_format_time(topic.start)}-{_format_time(topic.end)}",
        outline=parent_outline,
        llm=llm,
        max_tokens=max_tokens,
        explanation_style=explanation_style,
        coherence_guidance=coherence_guidance,
        fallback={
            "heading": subsections[0].heading,
            "summary": " ".join(sub.summary for sub in subsections[:2]).strip(),
            "key_points": [sub.heading for sub in subsections[:5]],
        },
    )

    return NoteSection(
        section_id=f"section_{topic_index:04d}",
        chunk_id=topic.chunk_ids[0],
        source_chunk_ids=topic.chunk_ids,
        timestamp_start=topic.start,
        timestamp_end=topic.end,
        heading=parent_data.get("heading", f"Topic {_format_time(topic.start)}"),
        summary=parent_data.get("summary", ""),
        key_points=parent_data.get("key_points", []),
        frames=_section_frames(
            frame_set,
            topic.start,
            topic.end,
            heading=parent_data.get("heading", f"Topic {_format_time(topic.start)}"),
            summary=parent_data.get("summary", ""),
            key_points=parent_data.get("key_points", []),
            vision_reranker=vision_reranker,
            keep=min(4, frame_rerank_keep + 1),
            max_candidates=max(frame_rerank_max_candidates, 5),
        ),
        subsections=subsections,
    )


def _synthesize_section_data(
    prompt_template: str,
    timestamp: str,
    outline: str,
    llm: LLMProvider,
    max_tokens: int,
    explanation_style: str,
    coherence_guidance: str,
    fallback: dict,
) -> dict:
    request = LLMRequest(
        prompt=prompt_template.format(
            timestamp=timestamp,
            outline=outline,
            style_guidance=_explanation_style_guidance(explanation_style),
            coherence_guidance=coherence_guidance,
        ),
        system=_SECTION_SYSTEM_PROMPT,
        max_tokens=max_tokens,
        temperature=0.2,
        response_format=_SECTION_RESPONSE_SCHEMA,
        extra_body=_LMSTUDIO_NO_THINKING,
    )
    try:
        response = llm.complete(request)
        text = response.text.strip()
        if not text:
            return fallback
        data = _parse_json_response(text)
        return fallback if _invalid_section_data(data) else data
    except Exception as exc:
        logger.warning("Section synthesis failed: %s; using fallback", exc)
        return fallback


def _generate_leaf_section(
    index: int,
    sc: ScoredChunk,
    llm: LLMProvider,
    frame_set: Optional[FrameSet],
    max_tokens: int,
    explanation_style: str,
    coherence_guidance: str,
    vision_reranker: Optional[VisionReranker],
    frame_rerank_keep: int,
    frame_rerank_max_candidates: int,
) -> NoteSection:
    prompt = _TOPIC_SECTION_TEMPLATE.format(
        timestamp=f"{sc.chunk.timestamp_str}-{_format_time(sc.chunk.end)}",
        outline=f"- [{sc.chunk.timestamp_str}] {sc.chunk.text[:2500]}",
        style_guidance=_explanation_style_guidance(explanation_style),
        coherence_guidance=coherence_guidance,
    )
    request = LLMRequest(
        prompt=prompt,
        system=_SECTION_SYSTEM_PROMPT,
        max_tokens=max_tokens,
        temperature=0.2,
        response_format=_SECTION_RESPONSE_SCHEMA,
        extra_body=_LMSTUDIO_NO_THINKING,
    )

    try:
        response = llm.complete(request)
        text = response.text.strip()
        if not text:
            logger.warning("LLM returned empty for %s; using fallback", sc.chunk.chunk_id)
            data = _fallback_section_data(sc)
        else:
            data = _parse_json_response(text)
            if _invalid_section_data(data):
                raise ValueError("Section data contained placeholder or empty fields")
    except Exception as exc:
        logger.warning("LLM generation failed for %s: %s; using fallback", sc.chunk.chunk_id, exc)
        data = _fallback_section_data(sc)

    return NoteSection(
        section_id=f"section_{index:04d}",
        chunk_id=sc.chunk.chunk_id,
        source_chunk_ids=[sc.chunk.chunk_id],
        timestamp_start=sc.chunk.start,
        timestamp_end=sc.chunk.end,
        heading=data.get("heading", f"Section {index + 1}"),
        summary=data.get("summary", ""),
        key_points=data.get("key_points", []),
        frames=_section_frames(
            frame_set,
            sc.chunk.start,
            sc.chunk.end,
            heading=data.get("heading", f"Section {index + 1}"),
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            vision_reranker=vision_reranker,
            keep=frame_rerank_keep,
            max_candidates=frame_rerank_max_candidates,
        ),
    )


def _group_topics(
    scored_chunks: list[ScoredChunk],
    chunk_summaries: list[ChunkSummary],
    frame_set: Optional[FrameSet],
    max_chunks_per_topic: int,
    boundary_threshold: float,
) -> list[TopicSpan]:
    topics: list[TopicSpan] = []
    current_items: list[tuple[ScoredChunk, ChunkSummary]] = [
        (scored_chunks[0], chunk_summaries[0])
    ]

    for idx in range(1, len(scored_chunks)):
        prev_sc, prev_summary = current_items[-1]
        next_sc = scored_chunks[idx]
        next_summary = chunk_summaries[idx]
        boundary_score = _score_boundary(prev_sc, next_sc, prev_summary, next_summary, frame_set)

        if len(current_items) >= max_chunks_per_topic or boundary_score >= boundary_threshold:
            topics.append(
                TopicSpan(
                    topic_id=f"topic_{len(topics):04d}",
                    items=current_items,
                    start=current_items[0][0].chunk.start,
                    end=current_items[-1][0].chunk.end,
                    boundary_strength=boundary_score,
                )
            )
            current_items = [(next_sc, next_summary)]
        else:
            current_items.append((next_sc, next_summary))

    if current_items:
        topics.append(
            TopicSpan(
                topic_id=f"topic_{len(topics):04d}",
                items=current_items,
                start=current_items[0][0].chunk.start,
                end=current_items[-1][0].chunk.end,
                boundary_strength=0.0,
            )
        )

    return topics


def _partition_topic(topic: TopicSpan, max_chunk_summaries_per_subsection: int) -> list[TopicSpan]:
    partitions: list[TopicSpan] = []
    current_items: list[tuple[ScoredChunk, ChunkSummary]] = []

    for index, item in enumerate(topic.items):
        current_items.append(item)
        should_split = len(current_items) >= max_chunk_summaries_per_subsection
        if not should_split and index + 1 < len(topic.items):
            _, current_summary = current_items[-1]
            _, next_summary = topic.items[index + 1]
            should_split = current_summary.transition in {"shift", "conclusion"} and len(current_items) >= 2

        if should_split:
            partitions.append(
                TopicSpan(
                    topic_id=f"{topic.topic_id}_{len(partitions):02d}",
                    items=current_items,
                    start=current_items[0][0].chunk.start,
                    end=current_items[-1][0].chunk.end,
                )
            )
            current_items = []

    if current_items:
        partitions.append(
            TopicSpan(
                topic_id=f"{topic.topic_id}_{len(partitions):02d}",
                items=current_items,
                start=current_items[0][0].chunk.start,
                end=current_items[-1][0].chunk.end,
            )
        )

    return partitions


def _score_boundary(
    prev_sc: ScoredChunk,
    next_sc: ScoredChunk,
    prev_summary: ChunkSummary,
    next_summary: ChunkSummary,
    frame_set: Optional[FrameSet],
) -> float:
    lexical_shift = 1.0 - _jaccard_similarity(
        _summary_keywords(prev_summary),
        _summary_keywords(next_summary),
    )

    transition_signal = 0.0
    if prev_summary.transition == "conclusion":
        transition_signal += 0.6
    if next_summary.transition == "shift":
        transition_signal += 0.8
    if _contains_transition_cue(next_sc.chunk.text[:250]):
        transition_signal += 0.5

    time_gap = max(0.0, next_sc.chunk.start - prev_sc.chunk.end)
    gap_signal = min(1.0, time_gap / 4.0)

    visual_signal = 0.0
    if frame_set:
        boundary_time = (prev_sc.chunk.end + next_sc.chunk.start) / 2
        frame = frame_set.get_frame_near(boundary_time, tolerance=4.0)
        if frame:
            visual_signal = frame.scene_diff_score or frame.content_score or 0.0

    score = (
        lexical_shift * 0.45
        + min(1.0, transition_signal) * 0.30
        + gap_signal * 0.10
        + visual_signal * 0.15
    )
    return max(0.0, min(1.0, score))


def _contains_transition_cue(text: str) -> bool:
    lower = text.lower()
    return any(re.search(pattern, lower) for pattern in _TRANSITION_PATTERNS)


def _coherence_context_for_chunk(scored_chunks: list[ScoredChunk], index: int) -> str:
    previous = scored_chunks[index - 1].chunk.text if index > 0 else ""
    upcoming = scored_chunks[index + 1].chunk.text if index + 1 < len(scored_chunks) else ""
    return _build_coherence_guidance(
        previous_summary=_compact_neighbor_text(previous),
        next_summary=_compact_neighbor_text(upcoming),
    )


def _coherence_context_for_topic(topics: list[TopicSpan], index: int) -> str:
    previous = topics[index - 1].summaries[-1].compact_text if index > 0 else ""
    upcoming = topics[index + 1].summaries[0].compact_text if index + 1 < len(topics) else ""
    current = " | ".join(summary.heading for summary in topics[index].summaries[:3])
    return _build_coherence_guidance(
        current_summary=current,
        previous_summary=previous,
        next_summary=upcoming,
    )


def _build_coherence_guidance(
    current_summary: str = "",
    previous_summary: str = "",
    next_summary: str = "",
) -> str:
    lines = [DEFAULT_COHERENCE_GUIDANCE]
    if current_summary:
        lines.append(f"Current section focus: {current_summary}")
    if previous_summary:
        lines.append(f"Previous context: {previous_summary}")
    if next_summary:
        lines.append(f"Upcoming context: {next_summary}")
    return "\n".join(lines)


def _compact_neighbor_text(text: str, limit: int = 180) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _explanation_style_guidance(style: str) -> str:
    normalized = (style or DEFAULT_EXPLANATION_STYLE).strip().lower().replace("-", "_")
    styles = {
        "concise": (
            "Be compact and direct. Prioritize the main takeaway over background detail. "
            "Keep summaries tight and avoid step-by-step teaching unless essential."
        ),
        "well_explained": (
            "Explain the idea clearly and coherently. Preserve important reasoning steps, "
            "define terms briefly when needed, and favor readability over compression."
        ),
        "educational": (
            "Write like a strong teacher. Make the explanation intuitive, connect steps logically, "
            "surface why each idea matters, and include enough context for a learner to follow."
        ),
    }
    guidance = styles.get(normalized)
    if guidance:
        return guidance
    logger.warning("Unknown explanation style '%s'; falling back to %s", style, DEFAULT_EXPLANATION_STYLE)
    default_key = DEFAULT_EXPLANATION_STYLE.strip().lower().replace("-", "_")
    return styles.get(default_key, styles["well_explained"])


def _summary_keywords(summary: ChunkSummary) -> set[str]:
    tokens: set[str] = set()
    for keyword in summary.keywords:
        tokens.update(_tokenize(keyword))
    if not tokens:
        tokens.update(_tokenize(summary.heading))
        tokens.update(_tokenize(summary.main_idea))
    return tokens


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9]{3,}", text.lower())
        if token not in _STOPWORDS
    }


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _section_frames(
    frame_set: Optional[FrameSet],
    start: float,
    end: float,
    heading: str,
    summary: str,
    key_points: list[str],
    vision_reranker: Optional[VisionReranker],
    keep: int = 2,
    max_candidates: int = 4,
) -> list[Frame]:
    if not frame_set:
        return []

    candidates = _frame_candidates(frame_set, start, end, max_candidates=max_candidates)
    if not candidates:
        return []

    if vision_reranker:
        candidate_pairs = [(f"frame_{idx}", frame.path) for idx, frame in enumerate(candidates)]
        try:
            ranked_ids = vision_reranker.rank_frames(
                section_heading=heading,
                section_summary=summary,
                key_points=key_points,
                candidates=candidate_pairs,
                keep=keep,
            )
            if ranked_ids:
                id_to_frame = {candidate_id: frame for candidate_id, frame in zip((cid for cid, _ in candidate_pairs), candidates)}
                ranked_frames = [id_to_frame[candidate_id] for candidate_id in ranked_ids if candidate_id in id_to_frame]
                if ranked_frames:
                    return sorted(ranked_frames[:keep], key=lambda frame: frame.timestamp)
        except VisionRerankerError as exc:
            logger.warning("Vision reranking failed: %s; using heuristic ranking", exc)

    return sorted(candidates[:keep], key=lambda frame: frame.timestamp)


def _frame_candidates(
    frame_set: FrameSet,
    start: float,
    end: float,
    max_candidates: int,
) -> list[Frame]:
    frames = frame_set.get_frames_in_range(start, end)
    if not frames:
        return []

    midpoint = (start + end) / 2
    duration = max(1.0, end - start)
    anchor_count = max(1, min(max_candidates, len(frames)))
    if anchor_count == 1:
        anchors = [midpoint]
    else:
        anchors = [
            start + (duration * index / (anchor_count - 1))
            for index in range(anchor_count)
        ]

    scored: list[tuple[float, Frame, float]] = []
    for frame in frames:
        proximity = 1.0 - min(1.0, abs(frame.timestamp - midpoint) / max(1.0, (end - start) / 2 + 2.0))
        content = frame.content_score or 0.0
        scene = frame.scene_diff_score or 0.0
        score = content * 0.55 + scene * 0.20 + proximity * 0.25
        nearest_anchor_distance = min(abs(frame.timestamp - anchor) for anchor in anchors)
        scored.append((score, frame, nearest_anchor_distance))

    scored.sort(key=lambda item: (-item[0], item[1].timestamp))

    selected: list[Frame] = []
    for anchor in anchors:
        anchor_best = [
            (score, frame)
            for score, frame, anchor_distance in scored
            if abs(frame.timestamp - anchor) <= max(4.0, duration / max(anchor_count * 2, 1))
        ]
        for _, frame in anchor_best:
            if any(abs(frame.timestamp - existing.timestamp) < 4.0 for existing in selected):
                continue
            selected.append(frame)
            break
        if len(selected) >= max_candidates:
            break

    if len(selected) < max_candidates:
        for _, frame, _ in sorted(scored, key=lambda item: (item[2], -item[0], item[1].timestamp)):
            if any(abs(frame.timestamp - existing.timestamp) < 4.0 for existing in selected):
                continue
            selected.append(frame)
            if len(selected) >= max_candidates:
                break

    if not selected:
        selected = [frame for _, frame, _ in scored[:max_candidates]]

    return selected


def _build_vision_reranker(
    enabled: bool,
    base_url: str,
    model: str,
) -> Optional[VisionReranker]:
    if not enabled:
        return None
    try:
        return VisionReranker(base_url=base_url, model=model)
    except Exception as exc:
        logger.warning("Vision reranker unavailable: %s", exc)
        return None


def _parallel_map(items, fn, max_workers: int):
    if max_workers <= 1 or len(items) <= 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(fn, items))


def _parse_json_response(text: str) -> dict:
    """Parse LLM response as JSON, stripping markdown fences and surrounding prose."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    match = re.search(r'\{[^{}]*"heading"[^{}]*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    match = re.search(r'\{[^{}]+\}', text)
    if match:
        return json.loads(match.group(0))
    raise json.JSONDecodeError("No JSON object found", text, 0)


def _fallback_chunk_summary(sc: ScoredChunk) -> dict:
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', sc.chunk.text) if s.strip()]
    heading = sentences[0][:50] if sentences else f"Chunk {_format_time(sc.chunk.start)}"
    keywords = list(_tokenize(sc.chunk.text))[:6]
    transition = "shift" if _contains_transition_cue(sc.chunk.text[:250]) else "continue"
    return {
        "heading": heading,
        "main_idea": ". ".join(sentences[:2])[:300] if sentences else sc.chunk.text[:300],
        "key_points": sentences[:4] if sentences else [sc.chunk.text[:200]],
        "keywords": keywords,
        "transition": transition,
    }


def _fallback_topic_data(summaries: list[ChunkSummary]) -> dict:
    lead = summaries[0]
    key_points: list[str] = []
    for summary in summaries[:4]:
        key_points.extend(summary.key_points[:1])
    return {
        "heading": lead.heading,
        "summary": " ".join(summary.main_idea for summary in summaries[:2]).strip(),
        "key_points": key_points[:5] or [lead.main_idea],
    }


def _fallback_section_data(sc: ScoredChunk) -> dict:
    text = sc.chunk.text.strip()
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    if not sentences:
        sentences = [text[:300]]

    summary = ". ".join(sentences[:2])
    if not summary.endswith("."):
        summary += "."

    key_points = sentences[1:5] if len(sentences) > 1 else []

    return {
        "heading": f"Section at {sc.chunk.timestamp_str}",
        "summary": summary[:500],
        "key_points": key_points,
    }


def _leaf_sections(sections: list[NoteSection]) -> list[NoteSection]:
    leaves: list[NoteSection] = []
    for section in sections:
        leaves.extend(section.leaf_sections())
    return leaves


def _format_time(seconds: float) -> str:
    return NoteSection._format_time(seconds)


def _invalid_chunk_summary_data(data: dict) -> bool:
    return (
        _is_placeholder_text(data.get("heading", ""))
        or _is_placeholder_text(data.get("main_idea", ""))
        or not [point for point in data.get("key_points", []) if not _is_placeholder_text(point)]
    )


def _invalid_section_data(data: dict) -> bool:
    return (
        _is_placeholder_text(data.get("heading", ""))
        or _is_placeholder_text(data.get("summary", ""))
        or not [point for point in data.get("key_points", []) if not _is_placeholder_text(point)]
    )


def _invalid_executive_summary_data(data: dict) -> bool:
    return (
        _is_placeholder_text(data.get("executive_summary", ""))
        or not [item for item in data.get("highlights", []) if not _is_placeholder_text(item)]
    )


def _is_placeholder_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not normalized:
        return True
    placeholders = {"...", "…", "tbd", "n/a", "na", "none", "summary", "highlights"}
    if normalized in placeholders:
        return True
    if re.fullmatch(r"[.\-•\s]+", normalized):
        return True
    return len(normalized) < 4
