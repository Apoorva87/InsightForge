"""Stage 9 — Storage: write notes.md, transcript.txt, frames/, and metadata.json."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from insightforge.models.output import FinalOutput
from insightforge.models.transcript import TranscriptResult
from insightforge.models.video import VideoMetadata
from insightforge.storage import paths as storage_paths
from insightforge.utils.logging import get_logger

logger = get_logger(__name__)


def write(
    output: FinalOutput,
    metadata: VideoMetadata,
    base_dir: Path,
    transcript: Optional[TranscriptResult] = None,
    audio_path: Optional[Path] = None,
    cleanup_work_dir: bool = True,
) -> FinalOutput:
    """Write all output artefacts to disk.

    Creates:
    - <base_dir>/<title>_<id>/notes.md
    - <base_dir>/<title>_<id>/transcript.txt  (full timestamped transcript)
    - <base_dir>/<title>_<id>/frames/ (copied from work dir)
    - <base_dir>/<title>_<id>/metadata.json

    Args:
        output: FinalOutput from Stage 8.
        metadata: VideoMetadata from Stage 1.
        base_dir: Root output directory.
        transcript: Optional aligned TranscriptResult to save in full.
        cleanup_work_dir: If True, delete the temp work directory after writing.

    Returns:
        FinalOutput with notes_path, transcript_path, frames_dir, and metadata_path set.
    """
    out_dir = storage_paths.job_output_dir(base_dir, output.video_id, output.title)
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Writing output to %s", out_dir)

    # 1. Write notes.md
    notes_file = storage_paths.notes_path(out_dir)
    notes_file.write_text(output.markdown_content, encoding="utf-8")
    logger.info("Wrote %s", notes_file)

    # 2. Write full transcript (plain text)
    transcript_file = storage_paths.transcript_path(out_dir)
    if transcript is not None:
        _write_transcript(transcript, transcript_file, metadata)
        logger.info("Wrote %s (%d segments)", transcript_file, len(transcript.segments))
    else:
        transcript_file = None

    # 2b. Write transcript.md (sectioned with inline frames)
    if output.transcript_md_content:
        transcript_md_file = out_dir / "transcript.md"
        transcript_md_file.write_text(output.transcript_md_content, encoding="utf-8")
        logger.info("Wrote %s", transcript_md_file)

    # 3. Copy frames
    dest_frames_dir = storage_paths.frames_dir(out_dir)
    if output.frames_dir and output.frames_dir.exists():
        if dest_frames_dir.exists():
            shutil.rmtree(dest_frames_dir)
        shutil.copytree(output.frames_dir, dest_frames_dir)
        frame_count = len(list(dest_frames_dir.glob("*.jpg")))
        logger.info("Copied %d frames to %s", frame_count, dest_frames_dir)
    else:
        dest_frames_dir.mkdir(exist_ok=True)

    # 3b. Copy video clips
    dest_clips_dir = storage_paths.clips_dir(out_dir)
    if output.clips_dir and output.clips_dir.exists():
        if dest_clips_dir.exists():
            shutil.rmtree(dest_clips_dir)
        shutil.copytree(output.clips_dir, dest_clips_dir)
        clip_count = len(list(dest_clips_dir.glob("*.mp4")))
        logger.info("Copied %d clips to %s", clip_count, dest_clips_dir)
    else:
        dest_clips_dir = None

    # 3c. Copy audio summary
    dest_audio_path = None
    if audio_path and audio_path.exists():
        dest_audio_path = storage_paths.audio_path(out_dir)
        shutil.copy2(audio_path, dest_audio_path)
        logger.info("Copied audio summary to %s", dest_audio_path)

    # 4. Write metadata.json
    meta_file = storage_paths.metadata_path(out_dir)
    meta_payload = {
        "video_id": output.video_id,
        "title": output.title,
        "channel": output.channel,
        "duration_seconds": output.duration_seconds,
        "section_count": output.section_count,
        "upload_date": metadata.upload_date,
        "thumbnail_url": metadata.thumbnail_url,
        "description": (metadata.description or "")[:500],
        "transcript_word_count": transcript.word_count if transcript else None,
        "transcript_language": transcript.language if transcript else None,
    }
    meta_file.write_text(json.dumps(meta_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote %s", meta_file)

    # 5. Optionally clean up work directory
    if cleanup_work_dir and metadata.work_dir and metadata.work_dir.exists():
        shutil.rmtree(metadata.work_dir)
        logger.debug("Cleaned up work directory: %s", metadata.work_dir)

    return FinalOutput(
        **{
            **output.model_dump(exclude={"notes_path", "transcript_path", "frames_dir", "clips_dir", "audio_path", "metadata_path"}),
            "notes_path": notes_file,
            "transcript_path": transcript_file,
            "frames_dir": dest_frames_dir,
            "clips_dir": dest_clips_dir,
            "audio_path": dest_audio_path,
            "metadata_path": meta_file,
        }
    )


def _write_transcript(
    transcript: TranscriptResult,
    path: Path,
    metadata: VideoMetadata,
) -> None:
    """Write the full timestamped transcript to a text file.

    Format:
        # Video Title
        # Channel: ...  |  Duration: ...

        [00:00] First segment text...
        [00:15] Second segment text...
        ...
    """
    lines: list[str] = []
    lines.append(f"# {metadata.title}")
    lines.append(f"# Channel: {metadata.channel}  |  Duration: {metadata.duration_human}")
    lines.append(f"# Source: {transcript.source}  |  Language: {transcript.language or 'auto'}")
    lines.append(f"# Segments: {len(transcript.segments)}  |  Words: {transcript.word_count}")
    lines.append("")

    for seg in transcript.segments:
        lines.append(f"[{seg.timestamp_str}] {seg.text}")

    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
