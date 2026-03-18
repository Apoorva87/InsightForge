"""Pipeline orchestrator — wires all 9 stages with concurrent fork at stages 5 & 6."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from insightforge.llm.router import LLMRouter
from insightforge.models.frame import FrameSet
from insightforge.models.output import FinalOutput
from insightforge.models.scoring import ScoredChunk
from insightforge.models.video import VideoJob
from insightforge.stages import (
    alignment,
    chunking,
    formatter,
    frames as frames_stage,
    importance,
    ingestion,
    llm_processing,
    transcript as transcript_stage,
)
from insightforge.storage import writer as storage_writer
from insightforge.utils import ffmpeg as ffmpeg_utils
from insightforge.utils.config import load_config
from insightforge.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


def run(job: VideoJob) -> FinalOutput:
    """Execute the full 9-stage InsightForge pipeline.

    Stage execution order:
      1. Ingestion         (VideoJob → VideoMetadata + video_path)
      2. Transcript        (→ TranscriptResult raw)
      3. Alignment         (→ TranscriptResult cleaned)
      4. Chunking          (→ ChunkBatch)
      [FORK]
      5. Frame Extraction  (I/O-bound, runs concurrently with Stage 6)
      6. Importance Scoring (LLM network-bound, runs concurrently with Stage 5)
      [JOIN]
      7. LLM Processing    (→ list[NoteSection])
      8. Formatter         (→ FinalOutput with markdown_content)
      9. Storage           (→ notes.md + frames/ + metadata.json on disk)

    Args:
        job: VideoJob input contract.

    Returns:
        FinalOutput with all artefact paths populated.

    Raises:
        PipelineError: On unrecoverable stage failures.
    """
    config = load_config(job.config_path)
    _configure_logging(config)
    logger.info("InsightForge pipeline starting — %s", job.url)

    llm_router = LLMRouter.from_config(config)

    # Stage 1 — Ingestion
    logger.info("[1/9] Ingestion")
    try:
        metadata, video_path = ingestion.run(job)
    except Exception as exc:
        raise PipelineError("ingestion", exc) from exc

    # Stage 2 — Transcript
    logger.info("[2/9] Transcript")
    transcript_cfg = config.get("transcript", {})
    try:
        raw_transcript = transcript_stage.run(
            metadata=metadata,
            video_path=video_path,
            prefer_manual=transcript_cfg.get("prefer_manual", True),
            whisper_model=transcript_cfg.get("whisper_model", "base"),
            language=transcript_cfg.get("language"),
        )
    except Exception as exc:
        raise PipelineError("transcript", exc) from exc

    # Stage 3 — Alignment
    logger.info("[3/9] Alignment")
    try:
        aligned_transcript = alignment.run(raw_transcript)
    except Exception as exc:
        raise PipelineError("alignment", exc) from exc

    # Stage 4 — Chunking
    logger.info("[4/9] Chunking")
    chunk_cfg = config.get("chunking", {})
    try:
        chunk_batch = chunking.run(
            aligned_transcript,
            strategy=chunk_cfg.get("strategy", "hybrid"),
            max_tokens=chunk_cfg.get("max_tokens", 800),
            min_tokens=chunk_cfg.get("min_tokens", 100),
            overlap_tokens=chunk_cfg.get("overlap_tokens", 50),
        )
    except Exception as exc:
        raise PipelineError("chunking", exc) from exc

    # Stages 5 & 6 — Fork: frames + importance scoring concurrently
    logger.info("[5+6/9] Frame extraction + Importance scoring (concurrent)")
    frames_cfg = config.get("frames", {})
    importance_cfg = config.get("importance", {})
    output_cfg = config.get("output", {})

    frames_enabled = job.frames_enabled and frames_cfg.get("enabled", True)

    frame_set: Optional[FrameSet] = None
    scored_chunks: list[ScoredChunk] = []

    work_frames_dir = (metadata.work_dir or Path("/tmp")) / "frames"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {}

        if frames_enabled:
            futures["frames"] = executor.submit(
                frames_stage.run,
                video_path=video_path,
                output_dir=work_frames_dir,
                chunk_batch=chunk_batch,
                extraction_mode=frames_cfg.get("extraction_mode", "scene_change"),
                interval_seconds=frames_cfg.get("interval_seconds", 30.0),
                scene_diff_threshold=frames_cfg.get("scene_diff_threshold", 0.3),
                top_k=frames_cfg.get("top_k", 20),
                max_width=frames_cfg.get("max_width", 1280),
                quality=frames_cfg.get("output_quality", 2),
            )

        futures["importance"] = executor.submit(
            importance.run,
            chunk_batch=chunk_batch,
            llm=llm_router,
            frame_set=None,  # visual scores computed after frames complete
            threshold=importance_cfg.get("threshold", 0.4),
            llm_weight=importance_cfg.get("llm_weight", 0.7),
            visual_weight=importance_cfg.get("visual_weight", 0.3),
            batch_size=importance_cfg.get("batch_size", 5),
        )

        for name, future in futures.items():
            try:
                result = future.result()
                if name == "frames":
                    frame_set = result
                elif name == "importance":
                    scored_chunks = result
            except Exception as exc:
                if name == "frames":
                    logger.warning("Frame extraction failed (non-fatal): %s", exc)
                    frame_set = None
                else:
                    raise PipelineError("importance", exc) from exc

    # Filter chunks by detail level
    filtered = importance.filter_by_detail(
        scored_chunks,
        detail=job.detail,
        threshold=importance_cfg.get("threshold", 0.4),
    )
    logger.info("[5+6] %d/%d chunks retained (detail=%s)", len(filtered), len(scored_chunks), job.detail)

    # Stage 7 — LLM Processing
    logger.info("[7/9] LLM processing")
    llm_proc_cfg = config.get("llm_processing", {})
    llm_max_tokens = llm_proc_cfg.get("max_tokens", 8192)
    try:
        sections = llm_processing.run(
            scored_chunks=filtered,
            llm=llm_router,
            frame_set=frame_set,
            max_tokens=llm_max_tokens,
        )
    except Exception as exc:
        raise PipelineError("llm_processing", exc) from exc

    # Stage 7b — Executive Summary
    logger.info("[7b/9] Executive summary")
    try:
        executive_summary = llm_processing.generate_executive_summary(
            sections=sections,
            llm=llm_router,
            title=metadata.title,
            channel=metadata.channel,
            max_tokens=llm_max_tokens,
        )
    except Exception as exc:
        logger.warning("Executive summary failed (non-fatal): %s", exc)
        executive_summary = ""

    # Stage 7c — Cut video clips for each section
    work_clips_dir = (metadata.work_dir or Path("/tmp")) / "clips"
    clips_created = False
    if ffmpeg_utils.check_ffmpeg():
        logger.info("[7c/9] Cutting video clips")
        segments = [
            (s.timestamp_start, s.timestamp_end, f"section_{s.section_id.split('_')[-1]}")
            for s in sections
        ]
        try:
            clip_paths = ffmpeg_utils.cut_video_clips(video_path, work_clips_dir, segments)
            clips_created = len(clip_paths) > 0
            logger.info("Cut %d video clips", len(clip_paths))
        except Exception as exc:
            logger.warning("Video clip cutting failed (non-fatal): %s", exc)

    # Stage 7d — Audio summary (optional)
    work_audio_path = None
    if job.audio_level is not None:
        logger.info("[7d/9] Audio summary (level=%.1f)", job.audio_level)
        try:
            audio_text = _build_audio_text(
                job.audio_level, executive_summary, sections, aligned_transcript
            )
            work_audio_path = (metadata.work_dir or Path("/tmp")) / "summary.mp3"
            ffmpeg_utils.generate_audio_summary(audio_text, work_audio_path)
            logger.info("Generated audio summary (%d chars)", len(audio_text))
        except Exception as exc:
            logger.warning("Audio summary failed (non-fatal): %s", exc)
            work_audio_path = None

    # Stage 8 — Formatter
    logger.info("[8/9] Formatting")
    try:
        final_output = formatter.run(
            sections=sections,
            metadata=metadata,
            frames_dir=work_frames_dir if frame_set else None,
            embed_frames_inline=output_cfg.get("embed_frames_inline", True),
            include_timestamp_index=output_cfg.get("include_timestamp_index", True),
            markdown_flavor=output_cfg.get("markdown_flavor", "github"),
            video_url=job.url,
            executive_summary=executive_summary,
            transcript=aligned_transcript,
            clips_dir=work_clips_dir if clips_created else None,
        )
    except Exception as exc:
        raise PipelineError("formatter", exc) from exc

    # Stage 9 — Storage
    logger.info("[9/9] Storage")
    storage_cfg = config.get("storage", {})
    base_dir = Path(output_cfg.get("base_dir", "./output"))
    if job.output_dir != Path("./output"):
        base_dir = job.output_dir
    try:
        final_output = storage_writer.write(
            output=final_output,
            metadata=metadata,
            base_dir=base_dir,
            transcript=aligned_transcript,
            audio_path=work_audio_path,
            cleanup_work_dir=storage_cfg.get("cleanup_work_dir", True),
        )
    except Exception as exc:
        raise PipelineError("storage", exc) from exc

    logger.info("Pipeline complete. Notes: %s", final_output.notes_path)
    if final_output.transcript_path:
        logger.info("Full transcript: %s", final_output.transcript_path)
    return final_output


def _build_audio_text(
    level: float,
    executive_summary: str,
    sections: list,
    transcript,
) -> str:
    """Build the text for audio TTS based on verbosity level.

    Args:
        level: 0.0 = executive summary only, 1.0 = full transcript.
        executive_summary: LLM-generated overview.
        sections: List of NoteSection objects.
        transcript: TranscriptResult with full segments.

    Returns:
        Text string to be spoken.
    """
    level = max(0.0, min(1.0, level))

    if level >= 1.0 and transcript and transcript.segments:
        # Full transcript
        return transcript.full_text

    if level <= 0.0:
        # Executive summary only
        if executive_summary:
            # Strip markdown formatting for speech
            import re
            text = re.sub(r"\*\*([^*]+)\*\*", r"\1", executive_summary)
            text = re.sub(r"^- ", "", text, flags=re.MULTILINE)
            return text
        # Fallback: section headings
        return ". ".join(s.heading for s in sections) + "."

    # Intermediate levels: blend section content
    parts = []

    if executive_summary and level >= 0.0:
        import re
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", executive_summary)
        text = re.sub(r"^- ", "", text, flags=re.MULTILINE)
        parts.append(text)

    if level >= 0.3:
        # Add section headings
        headings = ". ".join(f"Section: {s.heading}" for s in sections)
        parts.append(headings)

    if level >= 0.5:
        # Add section summaries
        for s in sections:
            parts.append(f"{s.heading}. {s.summary}")

    if level >= 0.7:
        # Add key points
        for s in sections:
            if s.key_points:
                points = ". ".join(s.key_points)
                parts.append(f"{s.heading}. {points}")

    return "\n\n".join(parts)


def _configure_logging(config: dict) -> None:
    log_cfg = config.get("logging", {})
    setup_logging(
        level=log_cfg.get("level", "INFO"),
        format=log_cfg.get("format", "text"),
    )


class PipelineError(Exception):
    """Raised when a pipeline stage fails unrecoverably."""

    def __init__(self, stage: str, cause: Exception) -> None:
        self.stage = stage
        self.cause = cause
        super().__init__(f"Pipeline failed at stage '{stage}': {cause}")
