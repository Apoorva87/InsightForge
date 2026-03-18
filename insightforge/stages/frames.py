"""Stage 5 — Frame Extraction: extract representative frames from the video.

Extraction strategy:
1. Primary extraction (scene_change, interval, or timestamp_aligned)
2. Supplementary extraction at topic transition points (chunk boundaries)
3. Content scoring — larger JPEG file size correlates with text/diagrams/code on screen
4. Rank by content_score so the most visually informative frames sort first
"""

from __future__ import annotations

from pathlib import Path

from insightforge.models.chunk import ChunkBatch
from insightforge.models.frame import Frame, FrameSet
from insightforge.utils import ffmpeg as ffmpeg_utils
from insightforge.utils.logging import get_logger

logger = get_logger(__name__)

# Frames within this many seconds of each other are considered duplicates
_DEDUP_THRESHOLD_SECONDS = 3.0


def run(
    video_path: Path,
    output_dir: Path,
    chunk_batch: ChunkBatch,
    extraction_mode: str = "scene_change",
    interval_seconds: float = 30.0,
    scene_diff_threshold: float = 0.3,
    top_k: int = 20,
    max_width: int = 1280,
    quality: int = 2,
) -> FrameSet:
    """Extract frames from the video using the configured strategy.

    After primary extraction, supplements with frames at topic transition
    points (chunk boundaries) and scores all frames by visual content richness.

    Args:
        video_path: Path to the downloaded video.
        output_dir: Directory where frames are written.
        chunk_batch: ChunkBatch from Stage 4 (used for transition points).
        extraction_mode: "interval" | "scene_change" | "timestamp_aligned".
        interval_seconds: Seconds between frames (interval mode only).
        scene_diff_threshold: Scene change threshold (scene_change mode only).
        top_k: Maximum number of frames to keep.
        max_width: Maximum frame width in pixels.
        quality: ffmpeg JPEG quality (1=best).

    Returns:
        FrameSet with extracted and scored frames.
    """
    if not ffmpeg_utils.check_ffmpeg():
        logger.warning("ffmpeg not found; skipping frame extraction")
        return FrameSet(frames=[], extraction_mode=extraction_mode, frames_dir=output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Extracting frames (mode=%s) to %s", extraction_mode, output_dir)

    # ---- 1. Primary extraction ----
    if extraction_mode == "interval":
        raw = ffmpeg_utils.extract_frames_interval(
            video_path, output_dir, interval_seconds, max_width, quality
        )
    elif extraction_mode == "scene_change":
        raw = ffmpeg_utils.extract_frames_scene_change(
            video_path, output_dir, scene_diff_threshold, max_width, quality
        )
    elif extraction_mode == "timestamp_aligned":
        timestamps = [chunk.midpoint for chunk in chunk_batch.chunks]
        raw = ffmpeg_utils.extract_frames_at_timestamps(
            video_path, output_dir, timestamps, max_width, quality
        )
    else:
        raise ValueError(f"Unknown extraction_mode: {extraction_mode!r}")

    # ---- 2. Supplement at topic transition points ----
    transition_ts = _get_transition_timestamps(chunk_batch)
    existing_ts = {ts for ts, _ in raw}
    missing_ts = [
        t for t in transition_ts
        if not any(abs(t - et) < _DEDUP_THRESHOLD_SECONDS for et in existing_ts)
    ]
    if missing_ts:
        try:
            extra = ffmpeg_utils.extract_frames_at_timestamps(
                video_path, output_dir, missing_ts, max_width, quality,
                prefix="tr_",
            )
            raw.extend(extra)
            logger.info("Added %d transition frames", len(extra))
        except Exception as exc:
            logger.warning("Transition frame extraction failed: %s", exc)

    # ---- 3. Deduplicate by timestamp proximity ----
    raw.sort(key=lambda x: x[0])
    deduped: list[tuple[float, Path]] = []
    for ts, path in raw:
        if deduped and abs(ts - deduped[-1][0]) < _DEDUP_THRESHOLD_SECONDS:
            # Keep the larger file (more visual content)
            if path.stat().st_size > deduped[-1][1].stat().st_size:
                deduped[-1] = (ts, path)
        else:
            deduped.append((ts, path))

    # ---- 4. Score frames by content richness (file size heuristic) ----
    # JPEG frames with text, code, or diagrams compress to larger files
    # than talking-head or plain background frames.
    file_sizes = [p.stat().st_size for _, p in deduped]
    max_size = max(file_sizes) if file_sizes else 1
    scored = [
        (ts, path, min(1.0, size / max_size))
        for (ts, path), size in zip(deduped, file_sizes)
    ]

    # Sort by content score descending to apply top_k to best frames
    scored.sort(key=lambda x: -x[2])
    kept = scored[:top_k]
    # Re-sort by timestamp for output
    kept.sort(key=lambda x: x[0])

    frames = [
        Frame(
            frame_id=f"frame_{i:04d}",
            timestamp=ts,
            path=path,
            content_score=score,
        )
        for i, (ts, path, score) in enumerate(kept)
    ]

    logger.info("Extracted %d frames (%d after dedup, %d kept)", len(raw), len(deduped), len(frames))
    return FrameSet(frames=frames, extraction_mode=extraction_mode, frames_dir=output_dir)


def _get_transition_timestamps(chunk_batch: ChunkBatch) -> list[float]:
    """Extract timestamps at chunk boundaries — these are topic transitions.

    For each chunk, we capture: start, midpoint, and a point 5s before the end.
    This ensures we get frames at topic transitions and within topic bodies.
    """
    timestamps: list[float] = []
    for chunk in chunk_batch.chunks:
        timestamps.append(chunk.start)
        timestamps.append(chunk.midpoint)
        # Capture near the end of the chunk too (might show concluding diagrams)
        if chunk.end - chunk.start > 15:
            timestamps.append(chunk.end - 5.0)
    return sorted(set(timestamps))
