"""Stage 4 — Chunking: split aligned transcript into token-bounded semantic chunks."""

from __future__ import annotations

from itertools import islice
from typing import Iterator

from insightforge.models.chunk import Chunk, ChunkBatch
from insightforge.models.transcript import TranscriptResult, TranscriptSegment
from insightforge.utils.logging import get_logger

logger = get_logger(__name__)


def run(
    result: TranscriptResult,
    strategy: str = "hybrid",
    max_tokens: int = 800,
    min_tokens: int = 100,
    overlap_tokens: int = 50,
) -> ChunkBatch:
    """Split a transcript into token-bounded chunks.

    Args:
        result: Aligned TranscriptResult from Stage 3.
        strategy: "token" | "sentence" | "hybrid". Hybrid uses sentence
                  boundaries with a token budget cap.
        max_tokens: Maximum tokens per chunk.
        min_tokens: Merge tiny trailing chunks if below this threshold.
        overlap_tokens: Number of tokens to overlap between adjacent chunks.

    Returns:
        ChunkBatch containing all chunks.
    """
    encode = _get_token_counter()

    if strategy == "token":
        chunks = _chunk_by_token(result.segments, encode, max_tokens, overlap_tokens)
    elif strategy == "sentence":
        chunks = _chunk_by_sentence(result.segments, encode, max_tokens, overlap_tokens)
    else:
        chunks = _chunk_hybrid(result.segments, encode, max_tokens, min_tokens, overlap_tokens)

    logger.info("Chunking: %d chunks from %d segments (strategy=%s)", len(chunks), len(result.segments), strategy)
    return ChunkBatch(chunks=chunks, strategy=strategy)


def _get_token_counter():
    """Return a callable that counts tokens in a string."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return lambda text: len(enc.encode(text))
    except ImportError:
        logger.debug("tiktoken not available; falling back to word-based token estimate")
        return lambda text: len(text.split())


def _chunk_by_token(
    segments: list[TranscriptSegment],
    encode,
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    """Simple token-budget chunking — fill until max_tokens, then start new chunk."""
    chunks: list[Chunk] = []
    buffer: list[TranscriptSegment] = []
    buffer_tokens = 0
    overlap_buffer: list[TranscriptSegment] = []

    for idx, seg in enumerate(segments):
        seg_tokens = encode(seg.text)
        if buffer_tokens + seg_tokens > max_tokens and buffer:
            chunks.append(_make_chunk(buffer, len(chunks), encode))
            # Carry over overlap
            overlap_buffer = _trim_overlap(buffer, overlap_tokens, encode)
            buffer = list(overlap_buffer)
            buffer_tokens = sum(encode(s.text) for s in buffer)

        buffer.append(seg)
        buffer_tokens += seg_tokens

    if buffer:
        chunks.append(_make_chunk(buffer, len(chunks), encode))

    return chunks


def _chunk_by_sentence(
    segments: list[TranscriptSegment],
    encode,
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    """Sentence-boundary chunking — split on punctuation, respect token budget."""
    import re

    sentence_end = re.compile(r"[.!?]+\s*$")
    chunks: list[Chunk] = []
    buffer: list[TranscriptSegment] = []
    buffer_tokens = 0

    for seg in segments:
        seg_tokens = encode(seg.text)
        if buffer_tokens + seg_tokens > max_tokens and buffer:
            # Find last sentence boundary in buffer
            cut = len(buffer)
            for i in range(len(buffer) - 1, -1, -1):
                if sentence_end.search(buffer[i].text):
                    cut = i + 1
                    break
            if cut == 0:
                cut = len(buffer)  # no boundary found — hard cut
            chunks.append(_make_chunk(buffer[:cut], len(chunks), encode))
            carry = _trim_overlap(buffer[:cut], overlap_tokens, encode)
            buffer = carry + buffer[cut:]
            buffer_tokens = sum(encode(s.text) for s in buffer)

        buffer.append(seg)
        buffer_tokens += seg_tokens

    if buffer:
        chunks.append(_make_chunk(buffer, len(chunks), encode))

    return chunks


def _chunk_hybrid(
    segments: list[TranscriptSegment],
    encode,
    max_tokens: int,
    min_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    """Hybrid strategy — prefer sentence boundaries, fall back to token budget."""
    chunks = _chunk_by_sentence(segments, encode, max_tokens, overlap_tokens)

    # Merge any chunk below min_tokens into its neighbour.
    # Pass 1: merge small chunks backward (into previous).
    # Pass 2: if the first chunk is still small, merge it forward.
    merged: list[Chunk] = []
    for chunk in chunks:
        if merged and chunk.token_count < min_tokens:
            prev = merged[-1]
            merged[-1] = _merge_chunks(prev, chunk)
        else:
            merged.append(chunk)

    # If the first chunk is still tiny, merge it forward into the second.
    if len(merged) >= 2 and merged[0].token_count < min_tokens:
        merged[1] = _merge_chunks(merged[0], merged[1])
        merged.pop(0)

    # Re-number
    for i, chunk in enumerate(merged):
        object.__setattr__(chunk, "chunk_id", f"chunk_{i:04d}")

    return merged


def _merge_chunks(a: Chunk, b: Chunk) -> Chunk:
    """Return a new Chunk that merges b into a."""
    return Chunk(
        chunk_id=a.chunk_id,
        text=a.text + " " + b.text,
        start=a.start,
        end=b.end,
        token_count=a.token_count + b.token_count,
        segment_indices=a.segment_indices + b.segment_indices,
    )


def _make_chunk(segments: list[TranscriptSegment], index: int, encode=None) -> Chunk:
    """Build a Chunk from a list of segments.

    Args:
        segments: Source segments.
        index: Sequential index used to generate chunk_id.
        encode: Token counter callable. If provided, gives accurate token counts.
    """
    text = " ".join(s.text for s in segments)
    token_count = encode(text) if encode is not None else len(text.split())
    return Chunk(
        chunk_id=f"chunk_{index:04d}",
        text=text,
        start=segments[0].start,
        end=segments[-1].end,
        token_count=token_count,
    )


def _trim_overlap(
    segments: list[TranscriptSegment],
    overlap_tokens: int,
    encode,
) -> list[TranscriptSegment]:
    """Return the trailing segments that fit within overlap_tokens budget."""
    result: list[TranscriptSegment] = []
    total = 0
    for seg in reversed(segments):
        t = encode(seg.text)
        if total + t > overlap_tokens:
            break
        result.insert(0, seg)
        total += t
    return result
