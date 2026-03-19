#!/usr/bin/env python3.11
"""Benchmark VLM inference: batch sizes, concurrency, and endpoint compatibility.

Tests LMStudio, Ollama, and MLX-based OpenAI-compatible servers.
Validates the exact endpoints InsightForge uses for VLM (vision reranking + enrichment).

Usage:
    python3.11 llm_testing/scripts/bench_vlm.py
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Server definitions
# ---------------------------------------------------------------------------

SERVERS = {
    "lmstudio": {
        "name": "LMStudio",
        "base_url": "http://localhost:1234/v1",
        "api_key": "lm-studio",
        "default_model": "qwen/qwen3-vl-8b",
        "description": "LMStudio local server (OpenAI-compatible)",
    },
    "ollama": {
        "name": "Ollama",
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
        "default_model": "llava:7b",
        "description": "Ollama server (OpenAI-compatible /v1 endpoint)",
    },
    "mlx": {
        "name": "MLX",
        "base_url": "http://localhost:8080/v1",
        "api_key": "mlx",
        "default_model": "mlx-community/Qwen2.5-VL-7B-Instruct-4bit",
        "description": "MLX-LM server (OpenAI-compatible)",
    },
}


def check_server(base_url: str, api_key: str) -> Optional[list[str]]:
    """Check if server is reachable and return available models."""
    try:
        import openai
        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        models = client.models.list()
        return [m.id for m in models.data]
    except Exception as exc:
        return None


def encode_image(path: Path) -> str:
    """Encode image as data URL."""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{data}"


def find_test_frames(n: int = 12) -> list[Path]:
    """Find frame images from existing output for testing."""
    output_dir = Path("output")
    if not output_dir.exists():
        return []
    for video_dir in sorted(output_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        frames_dir = video_dir / "frames"
        if frames_dir.exists():
            frames = sorted(frames_dir.glob("*.jpg"))[:n]
            if frames:
                return frames
    return []


# ---------------------------------------------------------------------------
# Test: Endpoint compatibility
# ---------------------------------------------------------------------------

def test_endpoint_compatibility(base_url: str, api_key: str, model: str) -> dict:
    """Test that the server supports the exact endpoints InsightForge uses.

    InsightForge VLM endpoints:
    - POST /v1/chat/completions (with image_url content type)
    - GET /v1/models
    """
    import openai

    results = {}
    client = openai.OpenAI(api_key=api_key, base_url=base_url)

    # Test 1: GET /v1/models
    try:
        models = client.models.list()
        results["GET /v1/models"] = {
            "status": "OK",
            "models": [m.id for m in models.data],
        }
    except Exception as exc:
        results["GET /v1/models"] = {"status": "FAIL", "error": str(exc)}

    # Test 2: POST /v1/chat/completions (text only)
    try:
        start = time.monotonic()
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with only: OK"}],
            max_tokens=10,
            temperature=0.0,
            timeout=30,
        )
        elapsed = (time.monotonic() - start) * 1000
        text = r.choices[0].message.content or ""
        results["POST /v1/chat/completions (text)"] = {
            "status": "OK",
            "response": text.strip()[:100],
            "latency_ms": round(elapsed),
        }
    except Exception as exc:
        results["POST /v1/chat/completions (text)"] = {"status": "FAIL", "error": str(exc)}

    # Test 3: POST /v1/chat/completions (with image)
    frames = find_test_frames(1)
    if frames:
        try:
            content = [
                {"type": "text", "text": "Describe this image in one sentence."},
                {"type": "image_url", "image_url": {"url": encode_image(frames[0])}},
            ]
            start = time.monotonic()
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                max_tokens=100,
                temperature=0.0,
                timeout=60,
            )
            elapsed = (time.monotonic() - start) * 1000
            text = r.choices[0].message.content or ""
            results["POST /v1/chat/completions (vision)"] = {
                "status": "OK",
                "response": text.strip()[:150],
                "latency_ms": round(elapsed),
            }
        except Exception as exc:
            results["POST /v1/chat/completions (vision)"] = {"status": "FAIL", "error": str(exc)}
    else:
        results["POST /v1/chat/completions (vision)"] = {
            "status": "SKIP",
            "reason": "No test frames found in output/",
        }

    return results


# ---------------------------------------------------------------------------
# Test: Batch size scaling
# ---------------------------------------------------------------------------

def test_batch_scaling(
    base_url: str,
    api_key: str,
    model: str,
    batch_sizes: list[int],
    frames: list[Path],
) -> list[dict]:
    """Test how per-frame cost changes with batch size."""
    import openai

    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    results = []

    for n in batch_sizes:
        if n > len(frames):
            break
        batch = frames[:n]
        ids = " ".join(f"f{i}" for i in range(n))
        content: list[dict] = [
            {
                "type": "text",
                "text": (
                    f"Classify each frame. Frame ids: {ids}. "
                    "Return JSON: {\"frames\": [{\"id\": \"f0\", \"frame_type\": \"slide\", "
                    "\"content_score\": 0.8, \"description\": \"...\"}]}"
                ),
            }
        ]
        for i, f in enumerate(batch):
            content.append({"type": "text", "text": f"Frame f{i}"})
            content.append({"type": "image_url", "image_url": {"url": encode_image(f)}})

        start = time.monotonic()
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                max_tokens=150 * n,
                temperature=0.0,
                timeout=120,
            )
            elapsed = (time.monotonic() - start) * 1000
            tokens = r.usage.completion_tokens if r.usage else 0
            results.append({
                "batch_size": n,
                "total_ms": round(elapsed),
                "per_frame_ms": round(elapsed / n),
                "tokens": tokens,
                "status": "OK",
            })
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            results.append({
                "batch_size": n,
                "total_ms": round(elapsed),
                "status": "FAIL",
                "error": str(exc)[:200],
            })

    return results


# ---------------------------------------------------------------------------
# Test: Concurrency scaling
# ---------------------------------------------------------------------------

def test_concurrency_scaling(
    base_url: str,
    api_key: str,
    model: str,
    concurrency_levels: list[int],
) -> list[dict]:
    """Test throughput at different concurrency levels (text-only for speed)."""
    import openai

    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    results = []

    def single_request(_label: str) -> float:
        start = time.monotonic()
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with only: OK"}],
            max_tokens=10,
            temperature=0.0,
            timeout=30,
        )
        return (time.monotonic() - start) * 1000

    for concurrency in concurrency_levels:
        try:
            start = time.monotonic()
            with ThreadPoolExecutor(max_workers=concurrency) as ex:
                latencies = list(ex.map(single_request, [f"c{i}" for i in range(concurrency)]))
            wall_ms = (time.monotonic() - start) * 1000
            results.append({
                "concurrency": concurrency,
                "wall_ms": round(wall_ms),
                "avg_latency_ms": round(sum(latencies) / len(latencies)),
                "throughput_rps": round(concurrency / (wall_ms / 1000), 2),
                "status": "OK",
            })
        except Exception as exc:
            results.append({
                "concurrency": concurrency,
                "status": "FAIL",
                "error": str(exc)[:200],
            })

    return results


# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------

def select_servers() -> list[dict]:
    """Discover available servers and let user choose which to test."""
    print("\n=== VLM Server Discovery ===\n")
    available = []

    for key, server in SERVERS.items():
        models = check_server(server["base_url"], server["api_key"])
        if models:
            status = f"ONLINE ({len(models)} models: {', '.join(models[:3])}{'...' if len(models) > 3 else ''})"
            available.append({**server, "key": key, "available_models": models})
        else:
            status = "OFFLINE"
        print(f"  [{key}] {server['name']:12s} {server['base_url']:35s} {status}")

    if not available:
        print("\n  No servers are reachable. Start LMStudio, Ollama, or an MLX server first.")
        return []

    print(f"\n  {len(available)} server(s) available.")
    choice = input("  Test which? (all / comma-separated keys / Enter=all): ").strip().lower()

    if not choice or choice == "all":
        return available

    keys = [k.strip() for k in choice.split(",")]
    return [s for s in available if s["key"] in keys]


def select_model(server: dict) -> str:
    """Let user pick a model from available ones."""
    models = server.get("available_models", [])
    if not models:
        return server["default_model"]

    if len(models) == 1:
        return models[0]

    print(f"\n  Available models on {server['name']}:")
    for i, m in enumerate(models):
        default_marker = " (default)" if m == server["default_model"] else ""
        print(f"    [{i+1}] {m}{default_marker}")

    choice = input(f"  Select model (1-{len(models)} / Enter=default): ").strip()
    if not choice:
        # Use default if available, otherwise first
        return server["default_model"] if server["default_model"] in models else models[0]
    try:
        idx = int(choice) - 1
        return models[idx]
    except (ValueError, IndexError):
        return models[0]


def select_tests() -> list[str]:
    """Let user choose which tests to run."""
    all_tests = [
        ("endpoints", "Endpoint compatibility (verifies InsightForge API calls work)"),
        ("batch", "Batch size scaling (1, 2, 4, 6, 8, 10, 12 frames per request)"),
        ("concurrency", "Concurrency scaling (1, 2, 4, 6, 8 parallel requests)"),
    ]
    print("\n=== Available Tests ===\n")
    for i, (key, desc) in enumerate(all_tests):
        print(f"  [{i+1}] {key:14s} {desc}")

    choice = input(f"\n  Run which? (all / comma-separated numbers / Enter=all): ").strip().lower()
    if not choice or choice == "all":
        return [k for k, _ in all_tests]

    selected = []
    for part in choice.split(","):
        try:
            idx = int(part.strip()) - 1
            selected.append(all_tests[idx][0])
        except (ValueError, IndexError):
            pass
    return selected or [k for k, _ in all_tests]


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def print_endpoint_results(server_name: str, results: dict) -> None:
    print(f"\n  --- {server_name}: Endpoint Compatibility ---")
    for endpoint, info in results.items():
        status = info["status"]
        marker = "PASS" if status == "OK" else status
        detail = ""
        if status == "OK" and "latency_ms" in info:
            detail = f" ({info['latency_ms']}ms)"
        elif status == "FAIL":
            detail = f" - {info.get('error', '')[:80]}"
        elif status == "SKIP":
            detail = f" - {info.get('reason', '')}"
        print(f"    {marker:5s} {endpoint}{detail}")


def print_batch_results(server_name: str, model: str, results: list[dict]) -> None:
    print(f"\n  --- {server_name} ({model}): Batch Size Scaling ---")
    print(f"    {'Batch':>5s}  {'Total':>8s}  {'Per-frame':>10s}  {'Tokens':>7s}  {'Status'}")
    print(f"    {'-----':>5s}  {'--------':>8s}  {'----------':>10s}  {'-------':>7s}  {'------'}")
    baseline = None
    for r in results:
        if r["status"] == "OK":
            if baseline is None:
                baseline = r["per_frame_ms"]
            speedup = f"{baseline / r['per_frame_ms']:.1f}x" if r["per_frame_ms"] > 0 else "-"
            print(
                f"    {r['batch_size']:5d}  {r['total_ms']:7d}ms  {r['per_frame_ms']:9d}ms  "
                f"{r.get('tokens', 0):7d}  OK ({speedup} vs batch=1)"
            )
        else:
            print(f"    {r['batch_size']:5d}  {r['total_ms']:7d}ms  {'':>10s}  {'':>7s}  FAIL: {r.get('error', '')[:60]}")


def print_concurrency_results(server_name: str, model: str, results: list[dict]) -> None:
    print(f"\n  --- {server_name} ({model}): Concurrency Scaling ---")
    print(f"    {'Conc':>4s}  {'Wall':>8s}  {'Avg Lat':>9s}  {'Throughput':>11s}  {'Status'}")
    print(f"    {'----':>4s}  {'--------':>8s}  {'---------':>9s}  {'-----------':>11s}  {'------'}")
    for r in results:
        if r["status"] == "OK":
            print(
                f"    {r['concurrency']:4d}  {r['wall_ms']:7d}ms  {r['avg_latency_ms']:8d}ms  "
                f"{r['throughput_rps']:9.1f} r/s  OK"
            )
        else:
            print(f"    {r['concurrency']:4d}  {'':>8s}  {'':>9s}  {'':>11s}  FAIL: {r.get('error', '')[:60]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark VLM servers for InsightForge")
    parser.add_argument("--non-interactive", action="store_true", help="Run all tests on all available servers")
    args = parser.parse_args()

    print("=" * 60)
    print("  InsightForge VLM Benchmark")
    print("=" * 60)

    if args.non_interactive:
        servers = []
        for key, server in SERVERS.items():
            models = check_server(server["base_url"], server["api_key"])
            if models:
                servers.append({**server, "key": key, "available_models": models})
        tests = ["endpoints", "batch", "concurrency"]
    else:
        servers = select_servers()
        if not servers:
            sys.exit(1)
        tests = select_tests()

    frames = find_test_frames(12)
    if not frames:
        print("\n  WARNING: No test frames found in output/. Batch scaling test will be skipped.")
        print("  Run InsightForge on a video first to generate frames.")

    for server in servers:
        if args.non_interactive:
            model = server["default_model"] if server["default_model"] in server["available_models"] else server["available_models"][0]
        else:
            model = select_model(server)

        print(f"\n{'=' * 60}")
        print(f"  Testing: {server['name']} ({server['base_url']})")
        print(f"  Model:   {model}")
        print(f"{'=' * 60}")

        if "endpoints" in tests:
            results = test_endpoint_compatibility(server["base_url"], server["api_key"], model)
            print_endpoint_results(server["name"], results)

        if "batch" in tests:
            if frames:
                results = test_batch_scaling(
                    server["base_url"], server["api_key"], model,
                    batch_sizes=[1, 2, 4, 6, 8, 10, 12],
                    frames=frames,
                )
                print_batch_results(server["name"], model, results)
            else:
                print(f"\n  --- {server['name']}: Batch Scaling SKIPPED (no frames) ---")

        if "concurrency" in tests:
            results = test_concurrency_scaling(
                server["base_url"], server["api_key"], model,
                concurrency_levels=[1, 2, 4, 6, 8],
            )
            print_concurrency_results(server["name"], model, results)

    print(f"\n{'=' * 60}")
    print("  Benchmark complete.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
