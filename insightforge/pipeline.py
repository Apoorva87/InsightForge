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
    config = _apply_job_overrides(config, job)
    config = _apply_educational_frame_overrides(config)
    config = _apply_educational_whisper_override(config)
    _configure_logging(config)
    logger.info("InsightForge pipeline starting — %s", job.url)

    llm_router = LLMRouter.from_config(config)

    # Stage 1 — Ingestion
    logger.info("[1/9] Ingestion (est ~15-45s, remaining ~depends on video length)")
    try:
        metadata, video_path = ingestion.run(job)
    except Exception as exc:
        raise PipelineError("ingestion", exc) from exc

    # Stage 2 — Transcript
    logger.info("[2/9] Transcript (%s)", _eta_note("transcript", metadata, config, job))
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
    logger.info("[3/9] Alignment (%s)", _eta_note("alignment", metadata, config, job))
    try:
        aligned_transcript = alignment.run(raw_transcript)
    except Exception as exc:
        raise PipelineError("alignment", exc) from exc

    # Stage 4 — Chunking
    logger.info("[4/9] Chunking (%s)", _eta_note("chunking", metadata, config, job))
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
    logger.info("[5+6/9] Frame extraction + Importance scoring (%s)", _eta_note("scoring", metadata, config, job))
    frames_cfg = config.get("frames", {})
    importance_cfg = config.get("importance", {})
    output_cfg = config.get("output", {})

    frames_enabled = job.frames_enabled and frames_cfg.get("enabled", True)
    # Skip LLM importance scoring when detail=high — all chunks are kept anyway
    skip_importance_llm = job.detail == "high"

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

        if skip_importance_llm:
            logger.info("detail=high: skipping LLM importance scoring (all chunks retained)")
            scored_chunks = importance.passthrough(chunk_batch)
        else:
            futures["importance"] = executor.submit(
                importance.run,
                chunk_batch=chunk_batch,
                llm=llm_router,
                frame_set=None,  # visual scores computed after frames complete
                threshold=importance_cfg.get("threshold", 0.4),
                llm_weight=importance_cfg.get("llm_weight", 0.7),
                visual_weight=importance_cfg.get("visual_weight", 0.3),
                batch_size=importance_cfg.get("batch_size", 5),
                parallel_workers=config.get("llm_processing", {}).get("parallel_workers", 4),
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

    if frame_set:
        scored_chunks = importance.apply_visual_scores(
            scored_chunks,
            frame_set=frame_set,
            llm_weight=importance_cfg.get("llm_weight", 0.7),
            visual_weight=importance_cfg.get("visual_weight", 0.3),
        )

    # VLM frame classification — replace JPEG-size heuristic with VLM-based scoring
    if frame_set and frames_cfg.get("vlm_rerank_enabled", True):
        frame_set = _classify_frames_with_vlm(frame_set, frames_cfg)

    # Filter chunks by detail level
    filtered = importance.filter_by_detail(
        scored_chunks,
        detail=job.detail,
        threshold=importance_cfg.get("threshold", 0.4),
    )
    logger.info("[5+6] %d/%d chunks retained (detail=%s)", len(filtered), len(scored_chunks), job.detail)

    # Stage 7 — LLM Processing
    logger.info("[7/9] LLM processing (%s)", _eta_note("llm_processing", metadata, config, job, chunk_count=len(filtered)))
    llm_proc_cfg = config.get("llm_processing", {})
    frames_cfg = config.get("frames", {})
    llm_max_tokens = llm_proc_cfg.get("max_tokens", 8192)
    try:
        sections = llm_processing.run(
            scored_chunks=filtered,
            llm=llm_router,
            frame_set=frame_set,
            max_tokens=llm_max_tokens,
            hierarchical=llm_proc_cfg.get("hierarchical", True),
            chunk_summary_max_tokens=llm_proc_cfg.get("chunk_summary_max_tokens", 1024),
            topic_summary_max_tokens=llm_proc_cfg.get("topic_summary_max_tokens", 2048),
            max_chunks_per_topic=llm_proc_cfg.get("max_chunks_per_topic", 4),
            max_chunk_summaries_per_subsection=llm_proc_cfg.get(
                "max_chunk_summaries_per_subsection", 3
            ),
            boundary_threshold=llm_proc_cfg.get("boundary_threshold", 0.58),
            explanation_style=llm_proc_cfg.get("explanation_style", "well_explained"),
            frame_rerank_enabled=frames_cfg.get("vlm_rerank_enabled", True),
            frame_rerank_base_url=frames_cfg.get("vlm_base_url", "http://localhost:1234/v1"),
            frame_rerank_model=frames_cfg.get("vlm_model", "qwen/qwen3-vl-8b"),
            frame_rerank_keep=frames_cfg.get("frames_per_section", 2),
            frame_rerank_max_candidates=frames_cfg.get("vlm_max_candidates", 4),
            parallel_workers=llm_proc_cfg.get("parallel_workers", 4),
        )
    except Exception as exc:
        raise PipelineError("llm_processing", exc) from exc

    # Stage 7b — Executive Summary
    logger.info("[7b/9] Executive summary (%s)", _eta_note("executive_summary", metadata, config, job))
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
        logger.info("[7c/9] Cutting video clips (%s)", _eta_note("clips", metadata, config, job, section_count=len(_leaf_sections(sections))))
        leaf_sections = _leaf_sections(sections)
        segments = [
            (s.timestamp_start, s.timestamp_end, s.section_id)
            for s in leaf_sections
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
        logger.info("[7d/9] Audio summary (level=%.1f, %s)", job.audio_level, _eta_note("audio", metadata, config, job))
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
    logger.info("[8/9] Formatting (%s)", _eta_note("formatting", metadata, config, job))
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
    logger.info("[9/9] Storage (%s)", _eta_note("storage", metadata, config, job))
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
            html_enabled=output_cfg.get("html_viewer", False),
            viewer_config=_viewer_config(config, llm_router),
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
        # Fallback: section headings (use leaves for hierarchical sections)
        leaves = _leaf_sections(sections)
        return ". ".join(s.heading for s in leaves) + "."

    # Intermediate levels: blend section content
    parts = []

    if executive_summary:
        import re
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", executive_summary)
        text = re.sub(r"^- ", "", text, flags=re.MULTILINE)
        parts.append(text)

    leaves = _leaf_sections(sections)

    if level >= 0.3:
        # Add section headings
        headings = ". ".join(f"Section: {s.heading}" for s in leaves)
        parts.append(headings)

    if level >= 0.5:
        # Add section summaries
        for s in leaves:
            parts.append(f"{s.heading}. {s.summary}")

    if level >= 0.7:
        # Add key points
        for s in leaves:
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


def _leaf_sections(sections: list) -> list:
    leaves = []
    for section in sections:
        leaves.extend(section.leaf_sections())
    return leaves


def _eta_note(
    stage: str,
    metadata,
    config: dict,
    job: VideoJob,
    chunk_count: int = 0,
    section_count: int = 0,
) -> str:
    """Return a rough stage/remaining ETA string for logs."""
    duration = metadata.duration_seconds
    stage_seconds = _estimate_stage_seconds(stage, duration, config, job, chunk_count, section_count)
    remaining_seconds = _estimate_remaining_seconds(stage, duration, config, job, chunk_count, section_count)
    return f"est ~{_format_seconds(stage_seconds)}, remaining ~{_format_seconds(remaining_seconds)}"


def _estimate_stage_seconds(
    stage: str,
    duration: float,
    config: dict,
    job: VideoJob,
    chunk_count: int,
    section_count: int,
) -> int:
    minutes = duration / 60.0
    parallel_workers = max(1, config.get("llm_processing", {}).get("parallel_workers", 4))

    estimates = {
        "transcript": int(20 + minutes * 3.0),
        "alignment": 5,
        "chunking": 8,
        "scoring": int(20 + max(1, chunk_count or 8) * 10),
        "llm_processing": int(25 + max(1, chunk_count or 8) * 22 / parallel_workers),
        "executive_summary": 15,
        "clips": int(10 + max(1, section_count or 4) * 3),
        "audio": int(20 + minutes * 1.2),
        "formatting": 8,
        "storage": 6,
    }
    if not (job.frames_enabled and config.get("frames", {}).get("enabled", True)) and stage == "scoring":
        estimates["scoring"] = int(12 + max(1, chunk_count or 8) * 8)
    return max(3, estimates.get(stage, 10))


def _estimate_remaining_seconds(
    current_stage: str,
    duration: float,
    config: dict,
    job: VideoJob,
    chunk_count: int,
    section_count: int,
) -> int:
    ordered_stages = [
        "transcript",
        "alignment",
        "chunking",
        "scoring",
        "llm_processing",
        "executive_summary",
        "clips",
        "audio",
        "formatting",
        "storage",
    ]
    try:
        start_index = ordered_stages.index(current_stage) + 1
    except ValueError:
        start_index = 0

    remaining = 0
    for stage in ordered_stages[start_index:]:
        if stage == "audio" and job.audio_level is None:
            continue
        remaining += _estimate_stage_seconds(stage, duration, config, job, chunk_count, section_count)
    return remaining


def _format_seconds(seconds: int) -> str:
    minutes, secs = divmod(max(0, int(seconds)), 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _apply_educational_frame_overrides(config: dict) -> dict:
    """Boost frame extraction/retention parameters when educational mode is active."""
    llm_proc_cfg = config.get("llm_processing", {})
    style = (llm_proc_cfg.get("explanation_style", "") or "").strip().lower().replace("-", "_")
    if style != "educational":
        return config

    config = {**config}
    frames_cfg = {**config.get("frames", {})}
    config["frames"] = frames_cfg

    # Use max/min so user overrides that are already more aggressive are preserved
    frames_cfg["top_k"] = max(frames_cfg.get("top_k", 30), 50)
    frames_cfg["frames_per_section"] = max(frames_cfg.get("frames_per_section", 2), 4)
    frames_cfg["vlm_max_candidates"] = max(frames_cfg.get("vlm_max_candidates", 4), 6)
    frames_cfg["scene_diff_threshold"] = min(frames_cfg.get("scene_diff_threshold", 0.2), 0.15)

    logger.debug(
        "Educational mode: boosted frame params — top_k=%d, frames_per_section=%d, "
        "vlm_max_candidates=%d, scene_diff_threshold=%.2f",
        frames_cfg["top_k"],
        frames_cfg["frames_per_section"],
        frames_cfg["vlm_max_candidates"],
        frames_cfg["scene_diff_threshold"],
    )
    return config


def _apply_educational_whisper_override(config: dict) -> dict:
    """Upgrade Whisper model when educational mode is active for better technical vocab."""
    llm_proc_cfg = config.get("llm_processing", {})
    style = (llm_proc_cfg.get("explanation_style", "") or "").strip().lower().replace("-", "_")
    if style != "educational":
        return config

    config = {**config}
    transcript_cfg = {**config.get("transcript", {})}
    config["transcript"] = transcript_cfg

    current_model = transcript_cfg.get("whisper_model", "distil-medium.en")
    # distil-large-v3 is the target for educational: faster than medium, better accuracy
    # Only upgrade if current model is weaker than distil-large-v3
    no_upgrade_models = {"distil-large-v3", "large", "large-v2", "large-v3"}
    if current_model not in no_upgrade_models:
        transcript_cfg["whisper_model"] = "distil-large-v3"
        logger.debug(
            "Educational mode: upgraded Whisper model from '%s' to 'distil-large-v3'",
            current_model,
        )

    return config


def _apply_job_overrides(config: dict, job: VideoJob) -> dict:
    """Apply CLI job overrides after config loading."""
    config = {**config}
    llm_cfg = {**config.get("llm", {})}
    output_cfg = {**config.get("output", {})}
    config["llm"] = llm_cfg
    config["output"] = output_cfg

    llm_cfg["mode"] = job.mode
    if job.html_enabled:
        output_cfg["html_viewer"] = True

    if job.model_override:
        if job.mode == "api":
            anthropic_cfg = {**llm_cfg.get("anthropic", {})}
            anthropic_cfg["model"] = job.model_override
            llm_cfg["anthropic"] = anthropic_cfg
        else:
            ollama_cfg = {**llm_cfg.get("ollama", {})}
            ollama_cfg["model"] = job.model_override
            llm_cfg["ollama"] = ollama_cfg

            if llm_cfg.get("lmstudio") is not None:
                lmstudio_cfg = {**llm_cfg.get("lmstudio", {})}
                lmstudio_cfg["model"] = job.model_override
                llm_cfg["lmstudio"] = lmstudio_cfg

    return config


def _classify_frames_with_vlm(frame_set: FrameSet, frames_cfg: dict) -> FrameSet:
    """Use VLM to classify frames by type and replace JPEG-size content_score heuristic."""
    from insightforge.utils.vision import VisionReranker

    try:
        reranker = VisionReranker(
            base_url=frames_cfg.get("vlm_base_url", "http://localhost:1234/v1"),
            model=frames_cfg.get("vlm_model", "qwen/qwen3-vl-8b"),
        )
    except Exception as exc:
        logger.warning("VLM frame classification unavailable: %s", exc)
        return frame_set

    frame_pairs = [(f.frame_id, f.path) for f in frame_set.frames if f.path.exists()]
    if not frame_pairs:
        return frame_set

    try:
        classifications = reranker.classify_frames(frame_pairs, batch_size=8)
    except Exception as exc:
        logger.warning("VLM frame classification failed: %s; keeping JPEG heuristic scores", exc)
        return frame_set

    updated_count = 0
    for frame in frame_set.frames:
        info = classifications.get(frame.frame_id)
        if info:
            frame.content_score = info["content_score"]
            frame.frame_type = info["frame_type"]
            frame.description = info.get("description", "")
            updated_count += 1

    logger.info("VLM classified %d/%d frames", updated_count, len(frame_set.frames))
    return frame_set


def _viewer_config(config: dict, llm_router: Optional["LLMRouter"] = None) -> dict:
    llm_cfg = config.get("llm", {})
    mode = llm_cfg.get("mode", "local")
    viewer = {"chat": {"enabled": False, "mode": mode}}
    if mode != "local":
        return viewer

    # Build candidate list in router order: LMStudio first, then Ollama.
    # Pick the first one that is actually reachable right now.
    candidates = []

    lmstudio_cfg = llm_cfg.get("lmstudio", {}) or {}
    if lmstudio_cfg:
        candidates.append(("lmstudio", lmstudio_cfg))

    ollama_cfg = llm_cfg.get("ollama", {}) or {}
    candidates.append(("ollama", ollama_cfg))

    # If we have the router, probe providers in order to match actual availability
    if llm_router is not None:
        provider_available = {}
        for provider in llm_router.providers:
            try:
                provider_available[provider.name] = provider.is_available()
            except Exception:
                provider_available[provider.name] = False

        for name, cfg in candidates:
            if provider_available.get(name, False):
                viewer["chat"] = _chat_entry(name, cfg)
                return viewer

    # Fallback: pick the first configured candidate (original behavior)
    for name, cfg in candidates:
        viewer["chat"] = _chat_entry(name, cfg)
        return viewer

    return viewer


def _chat_entry(provider_name: str, cfg: dict) -> dict:
    if provider_name == "lmstudio":
        return {
            "enabled": True,
            "provider": "lmstudio",
            "base_url": cfg.get("base_url", "http://localhost:1234/v1"),
            "model": cfg.get("model", "local-model"),
        }
    return {
        "enabled": True,
        "provider": "ollama",
        "base_url": cfg.get("base_url", "http://localhost:11434"),
        "model": cfg.get("model", "llama3.2"),
    }


class PipelineError(Exception):
    """Raised when a pipeline stage fails unrecoverably."""

    def __init__(self, stage: str, cause: Exception) -> None:
        self.stage = stage
        self.cause = cause
        super().__init__(f"Pipeline failed at stage '{stage}': {cause}")
