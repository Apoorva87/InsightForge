"""Local server for hosted HTML viewer and transcript-aware chat."""

from __future__ import annotations

import argparse
import json
import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from insightforge.llm.base import LLMRequest
from insightforge.llm.ollama_provider import OllamaProvider
from insightforge.llm.openai_provider import OpenAIProvider


class ViewerRequestHandler(SimpleHTTPRequestHandler):
    server_version = "InsightForgeViewer/0.1"

    def do_POST(self) -> None:
        if self.path != "/__insightforge/chat":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
            answer, used_web_search = _chat_answer(payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._send_json({"answer": answer, "used_web_search": used_web_search})

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _chat_answer(payload: dict) -> tuple[str, bool]:
    question = (payload.get("question") or "").strip()
    chat = payload.get("chat") or {}
    transcript = payload.get("transcript") or []
    history = payload.get("history") or []
    title = payload.get("title") or "video"
    use_web_search = bool(payload.get("web_search"))
    if not question:
        raise ValueError("Question is required.")
    if not chat.get("enabled"):
        raise ValueError("Chat is not enabled for this viewer.")

    transcript_text = "\n".join(
        f"[{line.get('timestamp', '')}] {line.get('text', '')}" for line in transcript
    )
    prompt = (
        f'Video title: {title}\n\n'
        "Transcript:\n"
        f"{transcript_text}\n\n"
        f"{_history_block(history)}"
        f"Question: {question}\n\n"
        "Answer using the transcript as the primary source. "
        "If the transcript is insufficient, say so briefly and then answer from general knowledge."
    )
    web_results = []
    if use_web_search:
        web_results = _web_search(question)
        if web_results:
            prompt += (
                "\n\nWeb results:\n"
                + "\n".join(f"- {result}" for result in web_results)
                + "\n\nUse the web results only as supporting context when the transcript is not enough."
            )
    request = LLMRequest(
        prompt=prompt,
        system=(
            "You answer questions about a video using the provided transcript first. "
            "Be concise, accurate, and explicit when the transcript does not fully support a claim. "
            "Do not reveal chain-of-thought or hidden reasoning. Return only the final answer."
        ),
        max_tokens=700,
        temperature=0.2,
    )

    provider_name = chat.get("provider")
    if provider_name == "lmstudio":
        provider = OpenAIProvider(
            api_key="lm-studio",
            base_url=chat.get("base_url", "http://localhost:1234/v1"),
            model=chat.get("model", "local-model"),
            provider_name="lmstudio",
        )
    elif provider_name == "ollama":
        provider = OllamaProvider(
            base_url=chat.get("base_url", "http://localhost:11434"),
            model=chat.get("model", "llama3.2"),
            timeout=120,
        )
    else:
        raise ValueError(f"Unsupported chat provider: {provider_name}")

    answer = provider.complete(request).text.strip()
    return _strip_reasoning(answer), bool(web_results)


def _history_block(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["Recent chat context:"]
    for turn in history[-8:]:
        role = str(turn.get("role") or "user").strip().lower()
        text = str(turn.get("text") or "").strip()
        if not text:
            continue
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {text}")
    lines.append("")
    return "\n".join(lines)


def _strip_reasoning(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"(?is)^reasoning\s*:.*?(?:\n\s*\n|$)", "", cleaned)
    cleaned = re.sub(r"(?is)^thoughts?\s*:.*?(?:\n\s*\n|$)", "", cleaned)
    return cleaned.strip()


def _web_search(query: str, limit: int = 5) -> list[str]:
    try:
        response = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=8.0,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return []

    data = response.json()
    results: list[str] = []
    abstract = (data.get("AbstractText") or "").strip()
    abstract_url = (data.get("AbstractURL") or "").strip()
    if abstract:
        results.append(f"{abstract} ({abstract_url})" if abstract_url else abstract)

    for topic in data.get("RelatedTopics", []):
        if len(results) >= limit:
            break
        if isinstance(topic, dict) and topic.get("Text"):
            text = str(topic["Text"]).strip()
            url = str(topic.get("FirstURL") or "").strip()
            results.append(f"{text} ({url})" if url else text)
            continue
        if isinstance(topic, dict) and isinstance(topic.get("Topics"), list):
            for nested in topic["Topics"]:
                if len(results) >= limit:
                    break
                text = str(nested.get("Text") or "").strip()
                url = str(nested.get("FirstURL") or "").strip()
                if text:
                    results.append(f"{text} ({url})" if url else text)
    return results[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve InsightForge HTML output with local chat.")
    parser.add_argument("--root", type=Path, required=True, help="Output root directory to serve")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    root = args.root.resolve()
    handler = lambda *handler_args, **handler_kwargs: ViewerRequestHandler(
        *handler_args, directory=str(root), **handler_kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
