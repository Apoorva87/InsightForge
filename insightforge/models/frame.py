"""Frame extraction data models."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class Frame(BaseModel):
    """A single extracted video frame."""

    frame_id: str                        # e.g. "frame_0007"
    timestamp: float                     # seconds from video start
    path: Path                           # absolute path to extracted JPEG/PNG
    scene_diff_score: Optional[float] = None   # 0.0–1.0 from scene detection
    content_score: Optional[float] = None      # 0.0–1.0, higher = more visual content (text/diagrams)
    nearest_chunk_id: Optional[str] = None     # linked chunk after alignment
    description: Optional[str] = None          # VLM-generated description of visual content
    frame_type: Optional[str] = None           # VLM-classified: slide/diagram/code/talking_head/transition/other
    ocr_text: Optional[str] = None             # VLM-extracted readable text/equations/code from frame

    @property
    def timestamp_str(self) -> str:
        total = int(self.timestamp)
        h, remainder = divmod(total, 3600)
        m, s = divmod(remainder, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @property
    def markdown_ref(self) -> str:
        """Return a relative markdown image reference."""
        return f"![Frame at {self.timestamp_str}]({self.path.name})"


class FrameSet(BaseModel):
    """All frames extracted for a video job."""

    frames: list[Frame]
    extraction_mode: str = "scene_change"   # interval | scene_change | timestamp_aligned
    frames_dir: Optional[Path] = None

    def __len__(self) -> int:
        return len(self.frames)

    def get_frame_near(self, timestamp: float, tolerance: float = 5.0) -> Optional[Frame]:
        """Return the closest frame within `tolerance` seconds of `timestamp`."""
        candidates = [f for f in self.frames if abs(f.timestamp - timestamp) <= tolerance]
        if not candidates:
            return None
        return min(candidates, key=lambda f: abs(f.timestamp - timestamp))

    def get_frames_in_range(self, start: float, end: float, padding: float = 3.0) -> list[Frame]:
        """Return all frames whose timestamp falls within [start-padding, end+padding].

        Frames are sorted by content_score (best first) then by timestamp.
        """
        matches = [
            f for f in self.frames
            if (start - padding) <= f.timestamp <= (end + padding)
        ]
        # Sort: high content_score first, then by timestamp
        matches.sort(
            key=lambda f: (-(f.content_score or 0.0), f.timestamp)
        )
        return matches
