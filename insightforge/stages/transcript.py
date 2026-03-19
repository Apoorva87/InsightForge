"""Stage 2 — Transcript: extract transcript from video or YouTube subtitles."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from insightforge.models.transcript import TranscriptResult, TranscriptSegment
from insightforge.models.video import VideoMetadata
from insightforge.utils.logging import get_logger

logger = get_logger(__name__)


def run(
    metadata: VideoMetadata,
    video_path: Path,
    prefer_manual: bool = True,
    whisper_model: str = "distil-medium.en",
    language: Optional[str] = None,
) -> TranscriptResult:
    """Extract a timestamped transcript.

    Preference order (when prefer_manual=True):
      1. YouTube manual subtitles (via yt-dlp)
      2. YouTube auto-generated captions
      3. Whisper transcription of the downloaded audio

    Args:
        metadata: VideoMetadata from Stage 1.
        video_path: Path to downloaded video file.
        prefer_manual: Whether to prefer YouTube's own subtitles.
        whisper_model: Whisper model size for fallback transcription.
        language: Language hint for Whisper (None = auto-detect).

    Returns:
        TranscriptResult with raw timestamped segments.
    """
    if prefer_manual:
        result = _try_youtube_transcript(metadata.video_id)
        if result is not None:
            logger.info("Using YouTube transcript (%s segments)", len(result.segments))
            return result

    logger.info("Falling back to Whisper model=%s", whisper_model)
    return _transcribe_whisper(video_path, whisper_model, language)


def _try_youtube_transcript(video_id: str) -> Optional[TranscriptResult]:
    """Attempt to fetch transcript from YouTube's subtitle API.

    Returns None if no subtitles are available.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled  # type: ignore[import]
    except ImportError:
        logger.debug("youtube-transcript-api not installed; skipping manual transcript")
        return None

    try:
        raw = YouTubeTranscriptApi.get_transcript(video_id)
        segments = [
            TranscriptSegment(
                start=entry["start"],
                end=entry["start"] + entry["duration"],
                text=entry["text"].strip(),
            )
            for entry in raw
            if entry.get("text", "").strip()
        ]
        return TranscriptResult(segments=segments, source="youtube_manual")
    except Exception as exc:
        logger.debug("YouTube transcript unavailable for %s: %s", video_id, exc)
        return None


def _transcribe_whisper(
    video_path: Path,
    model_size: str = "base",
    language: Optional[str] = None,
) -> TranscriptResult:
    """Transcribe audio using faster-whisper.

    Args:
        video_path: Path to the video/audio file.
        model_size: Whisper model size.
        language: Language code hint (or None for auto-detect).

    Returns:
        TranscriptResult from Whisper output.
    """
    try:
        from faster_whisper import WhisperModel, BatchedInferencePipeline  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "faster-whisper is required for local transcription. "
            "Install with: pip install faster-whisper"
        ) from exc

    logger.info("Loading Whisper model: %s", model_size)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    # Use BatchedInferencePipeline for 2-3x speedup on long audio.
    # It parallelizes VAD-segmented chunks through the model internally.
    batched_model = BatchedInferencePipeline(model=model)
    logger.info("Using batched inference pipeline (batch_size=16)")

    segments_iter, info = batched_model.transcribe(
        str(video_path),
        language=language,
        beam_size=1,         # greedy decoding: ~3-5x faster than beam_size=5, minimal quality loss
        vad_filter=True,     # skip silence/non-speech — major speedup on long videos
        vad_parameters={
            "min_silence_duration_ms": 500,
        },
        batch_size=16,       # process 16 VAD segments simultaneously
    )
    detected_lang = info.language
    total_duration = info.duration

    segments = []
    last_log_time = 0.0
    for seg in segments_iter:
        segments.append(
            TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
                confidence=seg.avg_logprob,
            )
        )
        # Progress logging every 60 seconds of audio processed
        if seg.end - last_log_time >= 60.0:
            last_log_time = seg.end
            pct = (seg.end / total_duration * 100) if total_duration > 0 else 0
            logger.info(
                "Whisper progress: %.0f%% (%d segments, %.0fs / %.0fs)",
                pct, len(segments), seg.end, total_duration,
            )

    logger.info(
        "Whisper transcription complete: %d segments, language=%s",
        len(segments),
        detected_lang,
    )
    return TranscriptResult(segments=segments, source="whisper", language=detected_lang)
