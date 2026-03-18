"""Stage 1 — Ingestion: download video metadata and audio/video via yt-dlp."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Optional

from insightforge.models.video import VideoJob, VideoMetadata
from insightforge.utils.logging import get_logger

logger = get_logger(__name__)


def run(job: VideoJob) -> tuple[VideoMetadata, Path]:
    """Download video metadata and video file.

    Args:
        job: The VideoJob input contract.

    Returns:
        Tuple of (VideoMetadata, video_path). video_path points to the
        downloaded video file within a temporary work directory.

    Raises:
        IngestionError: If yt-dlp fails or the URL is invalid.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise ImportError("yt-dlp is required. Install with: pip install yt-dlp") from exc

    work_dir = Path(tempfile.mkdtemp(prefix="insightforge_"))
    logger.info("Work directory: %s", work_dir)

    ydl_opts = _build_ydl_opts(work_dir, job)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info: dict[str, Any] = ydl.extract_info(job.url, download=True)
    except Exception as exc:
        raise IngestionError(f"yt-dlp failed for URL {job.url!r}: {exc}") from exc

    video_id = info.get("id", "unknown")
    video_path = _find_downloaded_file(work_dir, video_id)

    metadata = VideoMetadata(
        video_id=video_id,
        title=info.get("title", "Untitled"),
        channel=info.get("uploader") or info.get("channel") or "Unknown",
        duration_seconds=float(info.get("duration") or 0),
        upload_date=info.get("upload_date"),
        description=info.get("description"),
        thumbnail_url=info.get("thumbnail"),
        video_path=video_path,
        work_dir=work_dir,
    )
    logger.info("Ingested: %s (%s)", metadata.title, metadata.duration_human)
    return metadata, video_path


def _build_ydl_opts(work_dir: Path, job: VideoJob) -> dict[str, Any]:
    """Build yt-dlp options dict."""
    return {
        "outtmpl": str(work_dir / "%(id)s.%(ext)s"),
        # Prefer a format with both video and audio; fall back to best
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "writeinfojson": False,
        "noplaylist": True,
    }


def _sanitise_filename(name: str) -> str:
    """Replace filesystem-unsafe characters with underscores."""
    import re
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name


def _find_downloaded_file(work_dir: Path, video_id: str) -> Path:
    """Locate the downloaded video file in work_dir."""
    for ext in ("mp4", "mkv", "webm", "m4a"):
        candidate = work_dir / f"{video_id}.{ext}"
        if candidate.exists():
            return candidate
    # Fallback: first file in directory
    files = list(work_dir.iterdir())
    if files:
        return files[0]
    raise IngestionError(f"No downloaded file found in {work_dir}")


class IngestionError(Exception):
    """Raised when Stage 1 ingestion fails."""
