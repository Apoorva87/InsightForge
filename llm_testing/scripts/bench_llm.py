#!/usr/bin/env python3.11
"""Benchmark LLM text inference: Ollama, LMStudio, and MLX servers.

Tests the exact endpoints InsightForge uses for text generation
(importance scoring, note synthesis, executive summary).

Usage:
    python3.11 llm_testing/scripts/bench_llm.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx


# ---------------------------------------------------------------------------
# Server definitions
# ---------------------------------------------------------------------------

SERVERS = {
    "ollama": {
        "name": "Ollama",
        "base_url": "http://localhost:11434",
        "api_type": "ollama",
        "default_model": "qwen2.5:14b",
        "description": "Ollama /api/generate endpoint",
    },
    "lmstudio": {
        "name": "LMStudio",
        "base_url": "http://localhost:1234/v1",
        "api_type": "openai",
        "api_key": "lm-studio",
        "default_model": "qwen/qwen3.5-9b",
        "description": "LMStudio OpenAI-compatible /v1/chat/completions",
    },
    "mlx": {
        "name": "MLX",
        "base_url": "http://localhost:8080/v1",
        "api_type": "openai",
        "api_key": "mlx",
        "default_model": "mlx-community/Qwen2.5-7B-Instruct-4bit",
        "description": "MLX-LM server OpenAI-compatible",
    },
}

# InsightForge-realistic prompts for benchmarking
PROMPTS = {
    "importance_scoring": {
        "system": "You are a precise note-taking assistant. Respond ONLY with valid JSON.",
        "prompt": (
            "Rate the importance of this transcript chunk for study notes.\n\n"
            "Chunk: \"Neural networks learn by adjusting weights through backpropagation. "
            "The gradient of the loss function with respect to each weight is computed using "
            "the chain rule. This allows the network to minimize the error between predicted "
            "and actual outputs over many training iterations.\"\n\n"
            "Respond with JSON: {\"importance\": 0.0-1.0, \"reason\": \"brief explanation\"}"
        ),
        "max_tokens": 512,
    },
    "note_synthesis": {
        "system": "You are a precise note-taking assistant. Produce concise, high-signal study notes. Respond ONLY with valid JSON.",
        "prompt": (
            "Generate study notes for this section.\n\n"
            "Timestamp: 05:30-08:45\n"
            "Outline:\n"
            "- Backpropagation computes gradients layer by layer\n"
            "- Chain rule allows efficient gradient computation\n"
            "- Stochastic gradient descent updates weights in mini-batches\n\n"
            "Respond with JSON:\n"
            "{\"heading\": \"...\", \"summary\": \"...\", \"key_points\": [\"...\"], "
            "\"formulas\": [], \"code_snippets\": [], \"examples\": []}"
        ),
        "max_tokens": 1024,
    },
}


def check_server_ollama(base_url: str) -> Optional[list[str]]:
    """Check Ollama server availability and return model list."""
    try:
        r = httpx.get(f"{base_url}/api/tags", timeout=5.0)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return None


def check_server_openai(base_url: str, api_key: str) -> Optional[list[str]]:
    """Check OpenAI-compatible server and return model list."""
    try:
        import openai
        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        models = client.models.list()
        return [m.id for m in models.data]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Ollama endpoint tests
# ---------------------------------------------------------------------------

def test_ollama_endpoints(base_url: str, model: str) -> dict:
    """Test Ollama-specific endpoints that InsightForge uses."""
    results = {}

    # GET /api/tags (used by OllamaProvider.is_available and cli.py check)
    try:
        start = time.monotonic()
        r = httpx.get(f"{base_url}/api/tags", timeout=5.0)
        r.raise_for_status()
        elapsed = (time.monotonic() - start) * 1000
        models = [m["name"] for m in r.json().get("models", [])]
        results["GET /api/tags"] = {
            "status": "OK",
            "latency_ms": round(elapsed),
            "models": models[:5],
        }
    except Exception as exc:
        results["GET /api/tags"] = {"status": "FAIL", "error": str(exc)[:100]}

    # POST /api/generate (used by OllamaProvider.complete)
    try:
        payload = {
            "model": model,
            "prompt": "Reply with only: OK",
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 10},
        }
        start = time.monotonic()
        r = httpx.post(f"{base_url}/api/generate", json=payload, timeout=30.0)
        r.raise_for_status()
        elapsed = (time.monotonic() - start) * 1000
        data = r.json()
        text = data.get("response", "")
        # Check for thinking model behavior
        has_thinking = bool(data.get("thinking"))
        results["POST /api/generate"] = {
            "status": "OK",
            "latency_ms": round(elapsed),
            "response": text.strip()[:100],
            "has_thinking_field": has_thinking,
            "input_tokens": data.get("prompt_eval_count"),
            "output_tokens": data.get("eval_count"),
        }
    except Exception as exc:
        results["POST /api/generate"] = {"status": "FAIL", "error": str(exc)[:100]}

    return results


def test_openai_endpoints(base_url: str, api_key: str, model: str) -> dict:
    """Test OpenAI-compatible endpoints that InsightForge uses."""
    import openai

    results = {}
    client = openai.OpenAI(api_key=api_key, base_url=base_url)

    # GET /v1/models
    try:
        start = time.monotonic()
        models = client.models.list()
        elapsed = (time.monotonic() - start) * 1000
        results["GET /v1/models"] = {
            "status": "OK",
            "latency_ms": round(elapsed),
            "models": [m.id for m in models.data][:5],
        }
    except Exception as exc:
        results["GET /v1/models"] = {"status": "FAIL", "error": str(exc)[:100]}

    # POST /v1/chat/completions
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
        results["POST /v1/chat/completions"] = {
            "status": "OK",
            "latency_ms": round(elapsed),
            "response": text.strip()[:100],
        }
    except Exception as exc:
        results["POST /v1/chat/completions"] = {"status": "FAIL", "error": str(exc)[:100]}

    return results


# ---------------------------------------------------------------------------
# Prompt benchmarks
# ---------------------------------------------------------------------------

def bench_ollama_prompt(base_url: str, model: str, prompt_cfg: dict) -> dict:
    """Benchmark a realistic InsightForge prompt via Ollama."""
    prompt = prompt_cfg["prompt"]
    if prompt_cfg.get("system"):
        prompt = f"System: {prompt_cfg['system']}\n\n{prompt}"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": prompt_cfg["max_tokens"],
        },
    }

    start = time.monotonic()
    try:
        r = httpx.post(f"{base_url}/api/generate", json=payload, timeout=120.0)
        r.raise_for_status()
        elapsed = (time.monotonic() - start) * 1000
        data = r.json()
        text = data.get("response", "")
        if not text.strip() and data.get("thinking"):
            text = "[thinking model — response in thinking field]"
        # Try to parse as JSON to verify quality
        is_valid_json = False
        try:
            json.loads(text)
            is_valid_json = True
        except (json.JSONDecodeError, ValueError):
            pass
        return {
            "status": "OK",
            "latency_ms": round(elapsed),
            "output_tokens": data.get("eval_count", 0),
            "input_tokens": data.get("prompt_eval_count", 0),
            "valid_json": is_valid_json,
            "response_preview": text.strip()[:200],
            "tokens_per_sec": round(data.get("eval_count", 0) / (elapsed / 1000), 1) if elapsed > 0 else 0,
        }
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return {"status": "FAIL", "latency_ms": round(elapsed), "error": str(exc)[:200]}


def bench_openai_prompt(base_url: str, api_key: str, model: str, prompt_cfg: dict) -> dict:
    """Benchmark a realistic InsightForge prompt via OpenAI-compatible endpoint."""
    import openai

    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    messages = []
    if prompt_cfg.get("system"):
        messages.append({"role": "system", "content": prompt_cfg["system"]})
    messages.append({"role": "user", "content": prompt_cfg["prompt"]})

    start = time.monotonic()
    try:
        r = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=prompt_cfg["max_tokens"],
            temperature=0.0,
            timeout=120,
        )
        elapsed = (time.monotonic() - start) * 1000
        text = r.choices[0].message.content or ""
        is_valid_json = False
        try:
            json.loads(text)
            is_valid_json = True
        except (json.JSONDecodeError, ValueError):
            pass
        out_tokens = r.usage.completion_tokens if r.usage else 0
        in_tokens = r.usage.prompt_tokens if r.usage else 0
        return {
            "status": "OK",
            "latency_ms": round(elapsed),
            "output_tokens": out_tokens,
            "input_tokens": in_tokens,
            "valid_json": is_valid_json,
            "response_preview": text.strip()[:200],
            "tokens_per_sec": round(out_tokens / (elapsed / 1000), 1) if elapsed > 0 else 0,
        }
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return {"status": "FAIL", "latency_ms": round(elapsed), "error": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Concurrency test
# ---------------------------------------------------------------------------

def test_concurrency(
    base_url: str,
    api_key: Optional[str],
    api_type: str,
    model: str,
    levels: list[int],
) -> list[dict]:
    """Test throughput at different concurrency levels."""
    results = []

    def single_request(_label: str) -> float:
        start = time.monotonic()
        if api_type == "ollama":
            r = httpx.post(
                f"{base_url}/api/generate",
                json={"model": model, "prompt": "Reply: OK", "stream": False,
                      "options": {"num_predict": 10, "temperature": 0.0}},
                timeout=30.0,
            )
            r.raise_for_status()
        else:
            import openai
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply: OK"}],
                max_tokens=10, temperature=0.0, timeout=30,
            )
        return (time.monotonic() - start) * 1000

    for n in levels:
        try:
            start = time.monotonic()
            with ThreadPoolExecutor(max_workers=n) as ex:
                latencies = list(ex.map(single_request, [f"c{i}" for i in range(n)]))
            wall_ms = (time.monotonic() - start) * 1000
            results.append({
                "concurrency": n,
                "wall_ms": round(wall_ms),
                "avg_latency_ms": round(sum(latencies) / len(latencies)),
                "throughput_rps": round(n / (wall_ms / 1000), 2),
                "status": "OK",
            })
        except Exception as exc:
            results.append({"concurrency": n, "status": "FAIL", "error": str(exc)[:200]})

    return results


# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------

def select_servers() -> list[dict]:
    print("\n=== LLM Server Discovery ===\n")
    available = []

    for key, server in SERVERS.items():
        if server["api_type"] == "ollama":
            models = check_server_ollama(server["base_url"])
        else:
            models = check_server_openai(server["base_url"], server.get("api_key", ""))
        if models:
            status = f"ONLINE ({len(models)} models: {', '.join(models[:3])}{'...' if len(models) > 3 else ''})"
            available.append({**server, "key": key, "available_models": models})
        else:
            status = "OFFLINE"
        print(f"  [{key}] {server['name']:12s} {server['base_url']:35s} {status}")

    if not available:
        print("\n  No servers are reachable.")
        return []

    print(f"\n  {len(available)} server(s) available.")
    choice = input("  Test which? (all / comma-separated keys / Enter=all): ").strip().lower()
    if not choice or choice == "all":
        return available
    keys = [k.strip() for k in choice.split(",")]
    return [s for s in available if s["key"] in keys]


def select_model(server: dict) -> str:
    models = server.get("available_models", [])
    if len(models) <= 1:
        return models[0] if models else server["default_model"]

    print(f"\n  Available models on {server['name']}:")
    for i, m in enumerate(models):
        default = " (default)" if m == server["default_model"] else ""
        print(f"    [{i+1}] {m}{default}")

    choice = input(f"  Select model (1-{len(models)} / Enter=default): ").strip()
    if not choice:
        return server["default_model"] if server["default_model"] in models else models[0]
    try:
        return models[int(choice) - 1]
    except (ValueError, IndexError):
        return models[0]


def select_tests() -> list[str]:
    all_tests = [
        ("endpoints", "Endpoint compatibility (verifies InsightForge API calls work)"),
        ("prompts", "Realistic prompt benchmarks (importance scoring, note synthesis)"),
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
            selected.append(all_tests[int(part.strip()) - 1][0])
        except (ValueError, IndexError):
            pass
    return selected or [k for k, _ in all_tests]


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def print_endpoint_results(name: str, results: dict) -> None:
    print(f"\n  --- {name}: Endpoint Compatibility ---")
    for endpoint, info in results.items():
        status = info["status"]
        marker = "PASS" if status == "OK" else status
        detail = f" ({info['latency_ms']}ms)" if "latency_ms" in info else ""
        if status == "FAIL":
            detail = f" - {info.get('error', '')[:80]}"
        print(f"    {marker:5s} {endpoint}{detail}")
        if status == "OK" and info.get("has_thinking_field"):
            print(f"          Note: thinking model detected (chain-of-thought in thinking field)")


def print_prompt_results(name: str, model: str, prompt_name: str, result: dict) -> None:
    print(f"\n  --- {name} ({model}): {prompt_name} ---")
    if result["status"] == "OK":
        print(f"    Latency:    {result['latency_ms']}ms")
        print(f"    Tokens:     {result.get('input_tokens', '?')} in / {result.get('output_tokens', '?')} out")
        print(f"    Speed:      {result.get('tokens_per_sec', '?')} tok/s")
        print(f"    Valid JSON: {result['valid_json']}")
        print(f"    Preview:    {result['response_preview'][:120]}")
    else:
        print(f"    FAIL: {result.get('error', '')[:120]}")


def print_concurrency_results(name: str, results: list[dict]) -> None:
    print(f"\n  --- {name}: Concurrency Scaling ---")
    print(f"    {'Conc':>4s}  {'Wall':>8s}  {'Avg Lat':>9s}  {'Throughput':>11s}")
    print(f"    {'----':>4s}  {'--------':>8s}  {'---------':>9s}  {'-----------':>11s}")
    for r in results:
        if r["status"] == "OK":
            print(f"    {r['concurrency']:4d}  {r['wall_ms']:7d}ms  {r['avg_latency_ms']:8d}ms  {r['throughput_rps']:9.1f} r/s")
        else:
            print(f"    {r['concurrency']:4d}  FAIL: {r.get('error', '')[:60]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark LLM text servers for InsightForge")
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("  InsightForge LLM Text Benchmark")
    print("=" * 60)

    if args.non_interactive:
        servers = []
        for key, server in SERVERS.items():
            if server["api_type"] == "ollama":
                models = check_server_ollama(server["base_url"])
            else:
                models = check_server_openai(server["base_url"], server.get("api_key", ""))
            if models:
                servers.append({**server, "key": key, "available_models": models})
        tests = ["endpoints", "prompts", "concurrency"]
    else:
        servers = select_servers()
        if not servers:
            sys.exit(1)
        tests = select_tests()

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
            if server["api_type"] == "ollama":
                results = test_ollama_endpoints(server["base_url"], model)
            else:
                results = test_openai_endpoints(server["base_url"], server.get("api_key", ""), model)
            print_endpoint_results(server["name"], results)

        if "prompts" in tests:
            for prompt_name, prompt_cfg in PROMPTS.items():
                if server["api_type"] == "ollama":
                    result = bench_ollama_prompt(server["base_url"], model, prompt_cfg)
                else:
                    result = bench_openai_prompt(server["base_url"], server.get("api_key", ""), model, prompt_cfg)
                print_prompt_results(server["name"], model, prompt_name, result)

        if "concurrency" in tests:
            results = test_concurrency(
                server["base_url"], server.get("api_key"), server["api_type"],
                model, levels=[1, 2, 4, 6, 8],
            )
            print_concurrency_results(server["name"], results)

    print(f"\n{'=' * 60}")
    print("  Benchmark complete.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
