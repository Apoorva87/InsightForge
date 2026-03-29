#!/usr/bin/env python3.11
"""Interactive runner for all InsightForge benchmarks.

Discovers what's available (servers, models, audio) and lets you
choose which benchmarks to run.

Usage:
    python3.11 llm_testing/scripts/run_all.py
    python3.11 llm_testing/scripts/run_all.py --non-interactive
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).parent
BENCHMARKS = [
    {
        "key": "vlm",
        "name": "VLM Vision Benchmark",
        "script": "bench_vlm.py",
        "description": "Batch scaling, concurrency, and endpoint tests for vision models (LMStudio/Ollama/MLX)",
    },
    {
        "key": "llm",
        "name": "LLM Text Benchmark",
        "script": "bench_llm.py",
        "description": "Endpoint compatibility, prompt benchmarks, concurrency for text models (Ollama/LMStudio/MLX)",
    },
    {
        "key": "whisper",
        "name": "Whisper STT Benchmark",
        "script": "bench_whisper.py",
        "description": "Model loading, sequential vs batched, batch size scaling for faster-whisper",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run InsightForge benchmarks")
    parser.add_argument("--non-interactive", action="store_true", help="Run all benchmarks non-interactively")
    args = parser.parse_args()

    print("=" * 60)
    print("  InsightForge Benchmark Suite")
    print("=" * 60)
    print()

    if args.non_interactive:
        selected = BENCHMARKS
    else:
        print("  Available benchmarks:\n")
        for i, bench in enumerate(BENCHMARKS):
            print(f"    [{i+1}] {bench['name']}")
            print(f"        {bench['description']}\n")

        print("  Enter benchmark numbers like '1,3' or use 'all'.")
        print("  Press Enter to run the full suite.")
        choice = input("  Run which benchmarks? ").strip().lower()
        if not choice or choice == "all":
            selected = BENCHMARKS
        else:
            selected = []
            for part in choice.split(","):
                try:
                    selected.append(BENCHMARKS[int(part.strip()) - 1])
                except (ValueError, IndexError):
                    pass
            if not selected:
                selected = BENCHMARKS

    extra_args = ["--non-interactive"] if args.non_interactive else []

    for bench in selected:
        script_path = SCRIPTS_DIR / bench["script"]
        print(f"\n{'#' * 60}")
        print(f"  Running: {bench['name']}")
        print(f"  Script:  {script_path}")
        print(f"{'#' * 60}\n")

        result = subprocess.run(
            [sys.executable, str(script_path)] + extra_args,
            cwd=Path(__file__).parent.parent.parent,  # InsightForge root
        )
        if result.returncode != 0:
            print(f"\n  WARNING: {bench['name']} exited with code {result.returncode}")

    print(f"\n{'=' * 60}")
    print("  All benchmarks complete.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
