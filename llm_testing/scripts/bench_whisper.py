#!/usr/bin/env python3.11
"""Benchmark Whisper STT: model sizes, batched vs sequential, compute types.

Tests faster-whisper with the exact configuration InsightForge uses.

Usage:
    python3.11 llm_testing/scripts/bench_whisper.py
    python3.11 llm_testing/scripts/bench_whisper.py --audio path/to/audio.wav
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Available configurations
# ---------------------------------------------------------------------------

MODELS = {
    "tiny": {"description": "Tiny (39M params) — fastest, lowest accuracy"},
    "base": {"description": "Base (74M params) — fast, decent accuracy"},
    "small": {"description": "Small (244M params) — balanced"},
    "distil-medium.en": {"description": "Distil-Medium English (~400M) — InsightForge default"},
    "distil-large-v3": {"description": "Distil-Large-v3 (~800M) — best quality distilled"},
    "medium": {"description": "Medium (769M params) — high accuracy, slower"},
    "large-v3": {"description": "Large-v3 (1.5B params) — highest accuracy, slowest"},
}

COMPUTE_TYPES = ["int8", "float16", "float32"]
BATCH_SIZES = [1, 4, 8, 16, 24, 32]


def find_test_audio() -> Optional[Path]:
    """Find a video/audio file from existing output to test with."""
    output_dir = Path("output")
    if not output_dir.exists():
        return None
    for video_dir in sorted(output_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        # Look for downloaded videos in work dir or output
        for pattern in ["*.mp4", "*.webm", "*.mkv", "*.wav", "*.m4a"]:
            for f in video_dir.glob(pattern):
                return f
            work = video_dir / "work"
            if work.exists():
                for f in work.glob(pattern):
                    return f
    return None


def check_faster_whisper() -> bool:
    """Check if faster-whisper is installed."""
    try:
        import faster_whisper
        print(f"  faster-whisper version: {faster_whisper.__version__}")
        return True
    except ImportError:
        print("  faster-whisper is NOT installed.")
        print("  Install with: pip install faster-whisper")
        return False


def check_ctranslate2() -> dict:
    """Get CTranslate2 info."""
    try:
        import ctranslate2
        import os
        return {
            "version": ctranslate2.__version__,
            "cpu_count": os.cpu_count(),
        }
    except ImportError:
        return {"version": "not installed", "cpu_count": None}


# ---------------------------------------------------------------------------
# Benchmark functions
# ---------------------------------------------------------------------------

def bench_model_load(model_name: str, compute_type: str = "int8") -> dict:
    """Benchmark model loading time."""
    from faster_whisper import WhisperModel

    start = time.monotonic()
    try:
        model = WhisperModel(model_name, device="cpu", compute_type=compute_type)
        elapsed = (time.monotonic() - start) * 1000
        return {"status": "OK", "load_ms": round(elapsed), "model": model_name, "compute_type": compute_type}
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return {"status": "FAIL", "load_ms": round(elapsed), "error": str(exc)[:200]}


def bench_transcribe(
    audio_path: Path,
    model_name: str,
    compute_type: str = "int8",
    use_batched: bool = False,
    batch_size: int = 16,
    max_duration: float = 60.0,
) -> dict:
    """Benchmark transcription of audio (first max_duration seconds).

    Args:
        audio_path: Path to audio/video file.
        model_name: Whisper model name.
        compute_type: int8, float16, or float32.
        use_batched: Whether to use BatchedInferencePipeline.
        batch_size: Batch size for batched mode.
        max_duration: Only transcribe first N seconds (for speed).
    """
    from faster_whisper import WhisperModel, BatchedInferencePipeline

    # Load model
    load_start = time.monotonic()
    model = WhisperModel(model_name, device="cpu", compute_type=compute_type)
    load_ms = (time.monotonic() - load_start) * 1000

    if use_batched:
        pipeline = BatchedInferencePipeline(model=model)
    else:
        pipeline = model

    # Transcribe
    transcribe_start = time.monotonic()
    try:
        kwargs = {
            "beam_size": 1,
            "vad_filter": True,
            "vad_parameters": {"min_silence_duration_ms": 500},
        }
        if use_batched:
            kwargs["batch_size"] = batch_size

        segments_iter, info = pipeline.transcribe(str(audio_path), **kwargs)

        segments = []
        audio_processed = 0.0
        for seg in segments_iter:
            segments.append(seg)
            audio_processed = seg.end
            if audio_processed >= max_duration:
                break

        elapsed = (time.monotonic() - transcribe_start) * 1000
        word_count = sum(len(seg.text.split()) for seg in segments)

        return {
            "status": "OK",
            "model": model_name,
            "compute_type": compute_type,
            "batched": use_batched,
            "batch_size": batch_size if use_batched else None,
            "load_ms": round(load_ms),
            "transcribe_ms": round(elapsed),
            "audio_seconds": round(audio_processed, 1),
            "segments": len(segments),
            "words": word_count,
            "realtime_factor": round(audio_processed / (elapsed / 1000), 2) if elapsed > 0 else 0,
            "language": info.language,
            "preview": " ".join(seg.text.strip() for seg in segments[:3])[:200],
        }
    except Exception as exc:
        elapsed = (time.monotonic() - transcribe_start) * 1000
        return {
            "status": "FAIL",
            "model": model_name,
            "transcribe_ms": round(elapsed),
            "error": str(exc)[:200],
        }


def bench_batch_sizes(
    audio_path: Path,
    model_name: str,
    batch_sizes: list[int],
    max_duration: float = 60.0,
) -> list[dict]:
    """Compare different batch sizes for BatchedInferencePipeline."""
    results = []

    # Also test non-batched as baseline
    print("    Testing sequential (no batching)...")
    result = bench_transcribe(
        audio_path, model_name, use_batched=False, max_duration=max_duration,
    )
    result["batch_size"] = "sequential"
    results.append(result)

    for bs in batch_sizes:
        print(f"    Testing batch_size={bs}...")
        result = bench_transcribe(
            audio_path, model_name, use_batched=True, batch_size=bs, max_duration=max_duration,
        )
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------

def select_models() -> list[str]:
    print("\n=== Available Whisper Models ===\n")
    model_list = list(MODELS.items())
    for i, (name, info) in enumerate(model_list):
        print(f"  [{i+1}] {name:22s} {info['description']}")

    print("\n  Enter model numbers like '4,5' or use 'all'.")
    print("  Press Enter to benchmark the InsightForge default: distil-medium.en")
    choice = input("  Test which models? ").strip().lower()

    if choice == "all":
        return [name for name, _ in model_list]
    if not choice:
        return ["distil-medium.en"]  # InsightForge default

    selected = []
    for part in choice.split(","):
        try:
            idx = int(part.strip()) - 1
            selected.append(model_list[idx][0])
        except (ValueError, IndexError):
            pass
    return selected or ["distil-medium.en"]


def select_tests() -> list[str]:
    all_tests = [
        ("load", "Model loading time"),
        ("transcribe", "Transcription benchmark (sequential vs batched)"),
        ("batch_scaling", "Batch size scaling (1, 4, 8, 16, 24, 32)"),
    ]
    print("\n=== Available Tests ===\n")
    for i, (key, desc) in enumerate(all_tests):
        print(f"  [{i+1}] {key:16s} {desc}")

    print("\n  Use Enter or 'all' to run every Whisper test.")
    choice = input("  Run which tests? ").strip().lower()
    if not choice or choice == "all":
        return [k for k, _ in all_tests]
    selected = []
    for part in choice.split(","):
        try:
            selected.append(all_tests[int(part.strip()) - 1][0])
        except (ValueError, IndexError):
            pass
    return selected or [k for k, _ in all_tests]


def select_duration() -> float:
    print("\n  This limits how much audio is processed during the benchmark.")
    choice = input("  Audio duration to test in seconds (Enter=60): ").strip()
    if not choice:
        return 60.0
    try:
        return float(choice)
    except ValueError:
        return 60.0


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def print_load_results(results: list[dict]) -> None:
    print(f"\n  --- Model Loading Time ---")
    print(f"    {'Model':22s}  {'Compute':8s}  {'Load Time':>10s}  {'Status'}")
    print(f"    {'-----':22s}  {'-------':8s}  {'----------':>10s}  {'------'}")
    for r in results:
        if r["status"] == "OK":
            print(f"    {r['model']:22s}  {r['compute_type']:8s}  {r['load_ms']:9d}ms  OK")
        else:
            print(f"    {r['model']:22s}  {r['compute_type']:8s}  {r['load_ms']:9d}ms  FAIL: {r.get('error', '')[:50]}")


def print_transcribe_result(r: dict) -> None:
    if r["status"] == "OK":
        mode = f"batched (bs={r['batch_size']})" if r["batched"] else "sequential"
        print(f"    Model:          {r['model']}")
        print(f"    Mode:           {mode}")
        print(f"    Load time:      {r['load_ms']}ms")
        print(f"    Transcribe:     {r['transcribe_ms']}ms")
        print(f"    Audio:          {r['audio_seconds']}s ({r['segments']} segments, {r['words']} words)")
        print(f"    Realtime factor: {r['realtime_factor']}x (>{1.0} means faster than realtime)")
        print(f"    Language:       {r['language']}")
        print(f"    Preview:        {r['preview'][:100]}")
    else:
        print(f"    FAIL: {r.get('error', '')[:120]}")


def print_batch_scaling(results: list[dict]) -> None:
    print(f"\n  --- Batch Size Scaling ---")
    print(f"    {'Batch':>10s}  {'Transcribe':>11s}  {'Audio':>7s}  {'RT Factor':>10s}  {'Speedup'}")
    print(f"    {'----------':>10s}  {'-----------':>11s}  {'-------':>7s}  {'----------':>10s}  {'-------'}")
    baseline_ms = None
    for r in results:
        if r["status"] == "OK":
            bs = str(r.get("batch_size", "seq"))
            if baseline_ms is None:
                baseline_ms = r["transcribe_ms"]
            speedup = f"{baseline_ms / r['transcribe_ms']:.2f}x" if r["transcribe_ms"] > 0 else "-"
            print(
                f"    {bs:>10s}  {r['transcribe_ms']:10d}ms  {r['audio_seconds']:6.1f}s  "
                f"{r['realtime_factor']:9.2f}x  {speedup}"
            )
        else:
            bs = str(r.get("batch_size", "seq"))
            print(f"    {bs:>10s}  FAIL: {r.get('error', '')[:60]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Whisper STT for InsightForge")
    parser.add_argument("--audio", type=Path, help="Path to audio/video file to test with")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--duration", type=float, default=60.0, help="Seconds of audio to transcribe")
    args = parser.parse_args()

    print("=" * 60)
    print("  InsightForge Whisper STT Benchmark")
    print("=" * 60)

    if not check_faster_whisper():
        sys.exit(1)

    ct2_info = check_ctranslate2()
    print(f"  CTranslate2:          {ct2_info['version']}")
    print(f"  CPU cores:            {ct2_info['cpu_count']}")

    # Find audio
    audio_path = args.audio
    if not audio_path:
        audio_path = find_test_audio()
    if audio_path:
        print(f"  Test audio:           {audio_path}")
        print(f"  Test duration:        {args.duration}s (of audio)")
    else:
        print("  No audio file found. Transcription tests will be skipped.")
        print("  Use --audio to specify a file, or run InsightForge first.")

    if args.non_interactive:
        models = ["distil-medium.en"]
        tests = ["load", "transcribe", "batch_scaling"]
        max_duration = args.duration
    else:
        models = select_models()
        tests = select_tests()
        max_duration = args.duration if args.audio else select_duration()

    for model_name in models:
        print(f"\n{'=' * 60}")
        print(f"  Model: {model_name}")
        print(f"  {MODELS.get(model_name, {}).get('description', '')}")
        print(f"{'=' * 60}")

        if "load" in tests:
            results = [bench_model_load(model_name, ct) for ct in ["int8"]]
            print_load_results(results)

        if audio_path and "transcribe" in tests:
            print(f"\n  --- Transcription Benchmark ---")

            print("\n  Sequential mode:")
            r = bench_transcribe(audio_path, model_name, use_batched=False, max_duration=max_duration)
            print_transcribe_result(r)

            print("\n  Batched mode (batch_size=16):")
            r = bench_transcribe(audio_path, model_name, use_batched=True, batch_size=16, max_duration=max_duration)
            print_transcribe_result(r)

        if audio_path and "batch_scaling" in tests:
            results = bench_batch_sizes(audio_path, model_name, BATCH_SIZES, max_duration=max_duration)
            print_batch_scaling(results)

    print(f"\n{'=' * 60}")
    print("  Benchmark complete.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
