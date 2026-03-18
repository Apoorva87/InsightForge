"""Video-related data models."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, HttpUrl, field_validator


class VideoJob(BaseModel):
    """Input contract for the pipeline — everything needed to kick off processing."""

    url: str
    mode: str = "local"           # "local" | "api"
    detail: str = "high"          # "high" | "low"
    frames_enabled: bool = True
    audio_level: Optional[float] = None   # None = no audio; 0.0–1.0 verbosity
    output_dir: Path = Path("./output")
    config_path: Optional[Path] = None
    model_override: Optional[str] = None

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ("local", "api"):
            raise ValueError(f"mode must be 'local' or 'api', got {v!r}")
        return v

    @field_validator("detail")
    @classmethod
    def validate_detail(cls, v: str) -> str:
        if v not in ("high", "low"):
            raise ValueError(f"detail must be 'high' or 'low', got {v!r}")
        return v


class VideoMetadata(BaseModel):
    """Metadata extracted from yt-dlp after ingestion."""

    video_id: str
    title: str
    channel: str
    duration_seconds: float
    upload_date: Optional[str] = None       # YYYYMMDD string from yt-dlp
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    video_path: Optional[Path] = None       # local path after download
    work_dir: Optional[Path] = None         # temp working directory for this job

    @property
    def duration_human(self) -> str:
        """Return duration as HH:MM:SS string."""
        total = int(self.duration_seconds)
        h, remainder = divmod(total, 3600)
        m, s = divmod(remainder, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
