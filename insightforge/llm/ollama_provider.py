"""Ollama LLM provider — calls /api/generate via httpx."""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

from insightforge.llm.base import LLMProvider, LLMProviderError, LLMRequest, LLMResponse


class OllamaProvider(LLMProvider):
    """Calls a local Ollama instance at `base_url`."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "ollama"

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send request to Ollama /api/generate endpoint."""
        prompt = request.prompt
        if request.system:
            prompt = f"System: {request.system}\n\n{prompt}"

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        if request.stop:
            payload["options"]["stop"] = request.stop

        start = time.monotonic()
        try:
            response = httpx.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMProviderError(self.name, f"HTTP error: {exc}", cause=exc) from exc

        elapsed_ms = (time.monotonic() - start) * 1000
        data = response.json()

        text = data.get("response", "")
        # Some thinking/reasoning models (e.g. GLM-4-flash) put chain-of-thought
        # in a "thinking" field and can exhaust max_tokens before producing a
        # "response". Fall back to extracting the answer from thinking text.
        if not text.strip() and data.get("thinking"):
            text = _extract_from_thinking(data["thinking"])

        return LLMResponse(
            text=text,
            model=self.model,
            provider=self.name,
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            latency_ms=elapsed_ms,
        )

    def is_available(self) -> bool:
        """Return True if Ollama server is reachable."""
        try:
            httpx.get(f"{self.base_url}/api/tags", timeout=5.0).raise_for_status()
            return True
        except Exception:
            return False


def _extract_from_thinking(thinking: str) -> str:
    """Extract a useful answer from a thinking model's reasoning trace.

    Looks for valid JSON objects (note sections or scores), then score patterns,
    then returns the last non-empty line as a last resort.
    """
    import json as _json

    # Look for JSON objects — prefer larger ones (note sections) over small ones (scores)
    json_candidates = []
    for match in re.finditer(r"\{[^{}]+\}", thinking):
        candidate = match.group(0)
        try:
            parsed = _json.loads(candidate)
            if isinstance(parsed, dict) and parsed:
                json_candidates.append((len(candidate), candidate, parsed))
        except (_json.JSONDecodeError, ValueError):
            continue

    if json_candidates:
        # Prefer JSON with note-section keys (heading/summary) — take largest matching
        for _, candidate, parsed in sorted(json_candidates, key=lambda x: -x[0]):
            if "heading" in parsed or "summary" in parsed:
                return candidate
        # Otherwise prefer JSON with a numeric score
        for _, candidate, parsed in reversed(json_candidates):
            if "score" in parsed and isinstance(parsed["score"], (int, float)):
                return candidate
        # Return last valid JSON as fallback
        return json_candidates[-1][1]

    # Look for "score: 0.8" / "Score = 0.8" / "0.8" near end of thinking
    score_match = re.search(r"[Ss]core[:\s=]+([0-9]+\.?[0-9]*)", thinking)
    if score_match:
        return f'{{"score": {score_match.group(1)}}}'

    # Look for a bare decimal near end of thinking (e.g. model just outputs "0.75")
    bare_match = re.search(r"\b(0\.[0-9]+|1\.0)\b", thinking[-200:])
    if bare_match:
        return f'{{"score": {bare_match.group(1)}}}'

    # Return last non-empty line as last resort
    lines = [line.strip() for line in thinking.splitlines() if line.strip()]
    return lines[-1] if lines else ""
