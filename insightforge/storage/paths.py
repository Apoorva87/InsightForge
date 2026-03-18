"""Path management — derive output paths for a given video job."""

from __future__ import annotations

import re
from pathlib import Path


def job_output_dir(base_dir: Path, video_id: str, title: str) -> Path:
    """Return the output directory for a video job.

    Format: <base_dir>/<sanitised_title>_<video_id>/

    Args:
        base_dir: Root output directory from config.
        video_id: YouTube video ID.
        title: Video title (sanitised for filesystem).

    Returns:
        Absolute Path for the job's output directory.
    """
    safe_title = _sanitise_filename(title)[:60]
    dir_name = f"{safe_title}_{video_id}"
    return base_dir.resolve() / dir_name


def notes_path(output_dir: Path) -> Path:
    """Return the path for the notes.md file."""
    return output_dir / "notes.md"


def frames_dir(output_dir: Path) -> Path:
    """Return the path for the frames/ subdirectory."""
    return output_dir / "frames"


def transcript_path(output_dir: Path) -> Path:
    """Return the path for the transcript.txt file."""
    return output_dir / "transcript.txt"


def clips_dir(output_dir: Path) -> Path:
    """Return the path for the clips/ subdirectory."""
    return output_dir / "clips"


def audio_path(output_dir: Path) -> Path:
    """Return the path for the summary.mp3 audio file."""
    return output_dir / "summary.mp3"


def metadata_path(output_dir: Path) -> Path:
    """Return the path for the metadata.json file."""
    return output_dir / "metadata.json"


def _sanitise_filename(name: str) -> str:
    """Replace filesystem-unsafe characters with underscores."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name
