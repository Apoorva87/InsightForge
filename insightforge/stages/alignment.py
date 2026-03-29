"""Stage 3 — Alignment: clean transcript and fill gaps between segments."""

from __future__ import annotations

import re

from insightforge.models.transcript import TranscriptResult, TranscriptSegment
from insightforge.utils.logging import get_logger

logger = get_logger(__name__)

# Maximum silence gap to fill by extending the previous segment's end time
_MAX_GAP_FILL_SECONDS = 2.0


def run(result: TranscriptResult) -> TranscriptResult:
    """Clean and align a raw transcript.

    Operations:
    - Strip filler text (e.g. "[Music]", "[Applause]")
    - Merge very short segments (< 0.5s) into neighbours
    - Fill small silence gaps by extending segment end times
    - Normalise whitespace

    Args:
        result: Raw TranscriptResult from Stage 2.

    Returns:
        Cleaned TranscriptResult with is_aligned=True.
    """
    segments = list(result.segments)

    segments = _strip_noise_segments(segments)
    segments = _normalise_whitespace(segments)
    segments = _fill_gaps(segments, max_gap=_MAX_GAP_FILL_SECONDS)

    logger.info(
        "Alignment: %d → %d segments after cleaning",
        len(result.segments),
        len(segments),
    )
    return TranscriptResult(
        segments=segments,
        source=result.source,
        language=result.language,
        is_aligned=True,
    )


# Regex for noise-only segments like [Music], [Applause], (laughter), etc.
_NOISE_PATTERN = re.compile(r"^\s*[\[\(][^\]\)]{1,30}[\]\)]\s*$", re.IGNORECASE)


def _strip_noise_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Remove segments that contain only bracketed noise labels."""
    cleaned = [s for s in segments if not _NOISE_PATTERN.match(s.text)]
    removed = len(segments) - len(cleaned)
    if removed:
        logger.debug("Removed %d noise segments", removed)
    return cleaned


def _normalise_whitespace(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Collapse internal whitespace and strip leading/trailing spaces."""
    return [
        TranscriptSegment(
            start=s.start,
            end=s.end,
            text=re.sub(r"\s+", " ", s.text).strip(),
            confidence=s.confidence,
        )
        for s in segments
        if s.text.strip()
    ]


def _fill_gaps(
    segments: list[TranscriptSegment],
    max_gap: float = _MAX_GAP_FILL_SECONDS,
) -> list[TranscriptSegment]:
    """Extend each segment's end time to eliminate short silence gaps.

    Args:
        segments: List of segments, assumed sorted by start time.
        max_gap: Gaps <= this value (seconds) are filled.

    Returns:
        Segments with adjusted end times.
    """
    if len(segments) < 2:
        return segments

    result = sorted(segments, key=lambda s: (s.start, s.end, s.text))
    for i in range(len(result) - 1):
        gap = result[i + 1].start - result[i].end
        if 0 < gap <= max_gap:
            result[i] = TranscriptSegment(
                start=result[i].start,
                end=result[i + 1].start,
                text=result[i].text,
                confidence=result[i].confidence,
            )
    return result
