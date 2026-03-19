"""FFmpeg utilities — frame extraction and scene change detection helpers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from insightforge.utils.logging import get_logger

logger = get_logger(__name__)


def check_ffmpeg() -> bool:
    """Return True if ffmpeg is available on PATH."""
    return shutil.which("ffmpeg") is not None


def extract_frames_interval(
    video_path: Path,
    output_dir: Path,
    interval_seconds: float = 30.0,
    max_width: int = 1280,
    quality: int = 2,
) -> list[tuple[float, Path]]:
    """Extract frames at a fixed time interval.

    Args:
        video_path: Path to the downloaded video file.
        output_dir: Directory where frame images are written.
        interval_seconds: Seconds between frames.
        max_width: Maximum frame width (height scaled proportionally).
        quality: JPEG quality level (ffmpeg -q:v, 1=best, 31=worst).

    Returns:
        List of (timestamp_seconds, frame_path) tuples.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(output_dir / "frame_%06d.jpg")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"fps=1/{interval_seconds},scale={max_width}:-2",
        "-q:v", str(quality),
        pattern,
    ]
    logger.debug("Running ffmpeg interval extraction: %s", " ".join(cmd))
    _run_ffmpeg(cmd)

    frames = []
    for path in sorted(output_dir.glob("frame_*.jpg")):
        # Derive timestamp from frame index (1-based)
        idx = int(path.stem.split("_")[1])
        timestamp = (idx - 1) * interval_seconds
        frames.append((timestamp, path))
    return frames


def extract_frames_scene_change(
    video_path: Path,
    output_dir: Path,
    threshold: float = 0.3,
    max_width: int = 1280,
    quality: int = 2,
) -> list[tuple[float, Path]]:
    """Extract frames at scene change boundaries using ffmpeg's select filter.

    Args:
        video_path: Path to the video file.
        output_dir: Directory for output frames.
        threshold: Scene diff threshold (0.0–1.0). Higher = fewer frames.
        max_width: Maximum frame width.
        quality: JPEG quality level.

    Returns:
        List of (timestamp_seconds, frame_path) tuples, sorted by timestamp.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(output_dir / "scene_%06d.jpg")

    # Use escaped comma for select filter compatibility across platforms
    vf = f"select=gt(scene\\,{threshold}),showinfo,scale={max_width}:-2"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", vf,
        "-vsync", "vfr",
        "-q:v", str(quality),
        pattern,
    ]
    logger.debug("Running ffmpeg scene change extraction: %s", " ".join(cmd))
    try:
        result = _run_ffmpeg(cmd, capture_stderr=True)
    except FFmpegError as exc:
        # Exit code 234 = nothing written (no frames above threshold).
        # Fall back to interval extraction so we always get at least some frames.
        logger.warning(
            "Scene change extraction produced no frames (threshold=%.2f); "
            "falling back to interval extraction.",
            threshold,
        )
        return extract_frames_interval(
            video_path, output_dir, interval_seconds=30.0,
            max_width=max_width, quality=quality,
        )

    timestamps = _parse_showinfo_timestamps(result.stderr or "")

    frames = []
    sorted_paths = sorted(output_dir.glob("scene_*.jpg"))
    for i, path in enumerate(sorted_paths):
        ts = timestamps[i] if i < len(timestamps) else float(i)
        frames.append((ts, path))

    if not frames:
        logger.warning("No scene change frames extracted; falling back to interval extraction.")
        return extract_frames_interval(
            video_path, output_dir, interval_seconds=30.0,
            max_width=max_width, quality=quality,
        )

    return frames


def extract_frames_at_timestamps(
    video_path: Path,
    output_dir: Path,
    timestamps: list[float],
    max_width: int = 1280,
    quality: int = 2,
    prefix: str = "ts_",
) -> list[tuple[float, Path]]:
    """Extract exactly one frame at each requested timestamp.

    Args:
        video_path: Path to the video file.
        output_dir: Directory for output frames.
        timestamps: List of times (seconds) to extract.
        max_width: Maximum frame width.
        quality: JPEG quality level.
        prefix: Filename prefix for output frames.

    Returns:
        List of (timestamp_seconds, frame_path) tuples.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, ts in enumerate(sorted(timestamps)):
        out_path = output_dir / f"{prefix}{i:06d}.jpg"
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(ts),
            "-i", str(video_path),
            "-vframes", "1",
            "-vf", f"scale={max_width}:-2",
            "-q:v", str(quality),
            str(out_path),
        ]
        _run_ffmpeg(cmd)
        frames.append((ts, out_path))
    return frames


def cut_video_clips(
    video_path: Path,
    output_dir: Path,
    segments: list[tuple[float, float, str]],
) -> list[Path]:
    """Cut video into clips for each segment.

    Args:
        video_path: Path to the source video.
        output_dir: Directory for output clips.
        segments: List of (start_seconds, end_seconds, clip_name) tuples.

    Returns:
        List of paths to the created clip files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    clips = []
    for start, end, name in segments:
        out_path = output_dir / f"{name}.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(video_path),
            "-to", str(end - start),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            str(out_path),
        ]
        try:
            _run_ffmpeg(cmd)
            clips.append(out_path)
        except FFmpegError as exc:
            logger.warning("Failed to cut clip %s: %s", name, exc)
    return clips


def generate_audio_summary(
    text: str,
    output_path: Path,
) -> Path:
    """Generate an MP3 audio file from text using text-to-speech.

    Tries macOS ``say`` command with ffmpeg conversion first, then falls back
    to ``pyttsx3`` for cross-platform support.

    Args:
        text: The text to convert to speech.
        output_path: Path for the output MP3 file.

    Returns:
        Path to the generated audio file.

    Raises:
        FFmpegError: If audio generation fails with all methods.
    """
    import tempfile

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Method 1: macOS `say` → AIFF → ffmpeg → MP3
    if shutil.which("say") and shutil.which("ffmpeg"):
        tmp_aiff = Path(tempfile.mktemp(suffix=".aiff"))
        try:
            subprocess.run(
                ["say", "-o", str(tmp_aiff), text],
                check=True,
                capture_output=True,
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", str(tmp_aiff),
                "-acodec", "libmp3lame",
                "-ab", "128k",
                str(output_path),
            ]
            _run_ffmpeg(cmd)
            return output_path
        except Exception as exc:
            logger.warning("macOS say+ffmpeg TTS failed: %s; trying pyttsx3", exc)
        finally:
            tmp_aiff.unlink(missing_ok=True)

    # Method 2: pyttsx3 (cross-platform offline TTS)
    try:
        import pyttsx3

        engine = pyttsx3.init()
        tmp_wav = Path(tempfile.mktemp(suffix=".wav"))
        try:
            engine.save_to_file(text, str(tmp_wav))
            engine.runAndWait()
            if shutil.which("ffmpeg"):
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(tmp_wav),
                    "-acodec", "libmp3lame",
                    "-ab", "128k",
                    str(output_path),
                ]
                _run_ffmpeg(cmd)
            else:
                shutil.copy2(tmp_wav, output_path)
            return output_path
        finally:
            tmp_wav.unlink(missing_ok=True)
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("pyttsx3 TTS failed: %s", exc)

    raise FFmpegError("No TTS method available. Install pyttsx3 or use macOS.")


def extract_frames_dense(
    video_path: Path,
    output_dir: Path,
    interval_seconds: float = 4.0,
    change_threshold: int = 5,
    max_width: int = 1280,
    quality: int = 2,
) -> list[tuple[float, Path]]:
    """Extract frames at fixed interval, then keep only visually distinct ones via pHash.

    Args:
        video_path: Path to the video file.
        output_dir: Directory for output frames.
        interval_seconds: Seconds between initial frame captures.
        change_threshold: Min pHash Hamming distance to consider a frame "changed".
            Lower = more sensitive (keeps more frames). Range 0-64.
        max_width: Maximum frame width.
        quality: JPEG quality level.

    Returns:
        List of (timestamp_seconds, frame_path) tuples for kept frames.
    """
    # Step 1: Extract all frames at interval
    raw = extract_frames_interval(
        video_path, output_dir, interval_seconds, max_width, quality
    )
    if len(raw) <= 1:
        return raw

    # Step 2: Compute pHash for each frame and filter by change
    hashes: list[tuple[float, Path, int]] = []
    for ts, path in raw:
        h = _compute_phash(path)
        hashes.append((ts, path, h))

    # Always keep first frame
    kept: list[tuple[float, Path]] = [(hashes[0][0], hashes[0][1])]
    last_kept_hash = hashes[0][2]

    for ts, path, h in hashes[1:]:
        dist = _hamming_distance(h, last_kept_hash)
        if dist >= change_threshold:
            kept.append((ts, path))
            last_kept_hash = h
        else:
            # Delete rejected frame to save disk space
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    logger.info(
        "Dense extraction: %d raw frames → %d after pHash dedup (threshold=%d)",
        len(raw), len(kept), change_threshold,
    )
    return kept


def _compute_phash(image_path: Path) -> int:
    """Compute a 64-bit perceptual hash of an image.

    Resizes to 8x8 grayscale, compares each pixel to the mean.
    Fast (~0.1ms per image) and robust to scaling/compression.
    """
    try:
        from PIL import Image
    except ImportError:
        # Fallback: use file size as a crude hash (always returns unique)
        return image_path.stat().st_size

    img = Image.open(image_path).convert("L").resize((8, 8), Image.LANCZOS)
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    return sum(1 << i for i, p in enumerate(pixels) if p > avg)


def _hamming_distance(hash1: int, hash2: int) -> int:
    """Count differing bits between two 64-bit hashes."""
    return bin(hash1 ^ hash2).count("1")


class FFmpegError(Exception):
    """Raised when an ffmpeg subprocess fails."""


def _run_ffmpeg(
    cmd: list[str],
    capture_stderr: bool = False,
) -> subprocess.CompletedProcess:
    """Run an ffmpeg command, raising FFmpegError on non-zero exit.

    Args:
        cmd: Command list for subprocess.run.
        capture_stderr: If True, capture stderr (needed for timestamp parsing).

    Returns:
        CompletedProcess result.
    """
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture_stderr else subprocess.DEVNULL,
        text=capture_stderr,
    )
    if result.returncode != 0:
        raise FFmpegError(
            f"ffmpeg exited with code {result.returncode}. "
            f"Command: {' '.join(cmd)}"
        )
    return result


def _parse_showinfo_timestamps(stderr: str) -> list[float]:
    """Parse PTS timestamps from ffmpeg showinfo filter stderr output."""
    import re

    pattern = re.compile(r"pts_time:([\d.]+)")
    return [float(m.group(1)) for m in pattern.finditer(stderr)]
