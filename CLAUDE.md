# InsightForge — Claude Working Context

This file is for Claude to read at the start of any session on this project.
It tracks milestone status, known issues, and what to do next.

**Execution log**: See `execution_log.md` for detailed per-session history.

---

## Project Summary

Local-first YouTube Knowledge Extractor. Converts a YouTube URL into structured
Markdown notes with embedded timestamped screenshots. Runs via Ollama/LMStudio
locally or Anthropic as API fallback.

**Runtime**: Python 3.11 (installed at `/opt/homebrew/bin/python3.11`)
**Install**: `python3.11 -m pip install -e ".[dev]"` from `InsightForge/`
**Tests**: `python3.11 -m pytest tests/ -q`

---

## Milestone Status

| # | Milestone | Status | Notes |
|---|-----------|--------|-------|
| M1 | Foundation (models, config, logging) | ✅ COMPLETE | 84 tests pass |
| M2 | LLM Layer (base + 3 providers + router) | ✅ COMPLETE | OllamaProvider handles thinking models |
| M3 | Ingestion + Transcript (stages 1–3) | ✅ COMPLETE | yt-dlp + Whisper validated live |
| M4 | Chunking + Importance (stages 4 + 6) | ✅ COMPLETE | GLM scoring works with 512-token budget |
| M5 | Visual Frame Pipeline (ffmpeg + stage 5) | ✅ COMPLETE | Scene change + interval fallback |
| M6 | LLM Processing + Output (stages 7 + 8) | ✅ COMPLETE | Full Markdown sections generated |
| M7 | Storage + Pipeline wiring | ✅ COMPLETE | Full 9-stage `pipeline.run()` works E2E |
| M8 | CLI + Integration test | ✅ COMPLETE | `insightforge process <url>` + `check` working |

---

## Live Environment

- **Python**: `/opt/homebrew/bin/python3.11`
- **ffmpeg**: `/opt/homebrew/bin/ffmpeg` (v8.0.1) ✅
- **yt-dlp**: available on PATH ✅
- **Ollama**: running on `http://localhost:11434` ✅
  - Available models: `glm-4.7-flash:latest` (text), `x/flux2-klein:4b-fp8`, `x/z-image-turbo:fp8`
  - **Default model in config**: `glm-4.7-flash:latest` (updated from llama3.2)
- **faster-whisper**: ✅ (base model downloaded to HuggingFace cache)
- **anthropic SDK**: ✅
- **openai SDK**: ✅
- **tiktoken**: ✅

---

## Architecture Quick Reference

```
insightforge/
├── cli.py              ← Typer CLI (insightforge process / insightforge check)
├── pipeline.py         ← 9-stage orchestrator, concurrent fork at stages 5+6
├── models/             ← Pydantic contracts: VideoJob, VideoMetadata,
│                          TranscriptResult, ChunkBatch, FrameSet,
│                          ScoredChunk, NoteSection, FinalOutput
├── stages/
│   ├── ingestion.py    ← Stage 1: yt-dlp download
│   ├── transcript.py   ← Stage 2: YouTube captions or faster-whisper
│   ├── alignment.py    ← Stage 3: clean + gap-fill transcript
│   ├── chunking.py     ← Stage 4: token-bounded semantic chunks (tiktoken)
│   ├── frames.py       ← Stage 5: ffmpeg frame extraction + fallback
│   ├── importance.py   ← Stage 6: LLM + visual importance scoring
│   ├── llm_processing.py ← Stage 7: generate NoteSection per chunk
│   └── formatter.py    ← Stage 8: assemble Markdown
├── llm/
│   ├── base.py         ← LLMProvider ABC, LLMRequest, LLMResponse
│   ├── ollama_provider.py  ← httpx to /api/generate + thinking model support
│   ├── anthropic_provider.py ← anthropic SDK
│   ├── openai_provider.py    ← OpenAI-compatible (also LMStudio)
│   └── router.py       ← LLMRouter: tries providers in order, falls back
├── storage/
│   ├── paths.py        ← derive output paths from video_id + title
│   └── writer.py       ← Stage 9: write notes.md, transcript.md, frames/, clips/, metadata.json
└── utils/
    ├── config.py       ← load + merge default.yaml + user yaml + env vars
    ├── logging.py      ← Rich console logger or JSON lines
    └── ffmpeg.py       ← frame extraction helpers (interval/scene/timestamp)
```

---

## LLM Provider Decision Matrix

| Mode | Primary | Fallback |
|------|---------|----------|
| `local` | Ollama (`http://localhost:11434`) | LMStudio (`http://localhost:1234/v1`) |
| `api` | Anthropic (env: `ANTHROPIC_API_KEY`) | — |

---

## Known Issues / Quirks

### GLM-4.7-flash (Ollama) — Thinking Model Behavior
- This is a reasoning/thinking model: it outputs chain-of-thought to `thinking` field,
  actual answer to `response` field in Ollama API.
- With token budgets > 512, it over-thinks and exhausts all tokens on reasoning,
  leaving `response` empty.
- **Fix in `ollama_provider.py`**: if `response` is empty and `thinking` has content,
  `_extract_from_thinking()` extracts the answer from the thinking trace.
- **Fix in `importance.py`**: uses 512 tokens max (sweet spot for GLM to conclude).
- **Fix in `llm_processing.py`**: uses 1024 tokens (longer output needed for JSON sections).

### ffmpeg Scene Change Detection
- Low-motion videos (e.g. static talking-head) produce 0 scene change frames.
- **Fix in `ffmpeg.py`**: `extract_frames_scene_change()` catches empty result and
  falls back to `extract_frames_interval()`.

### Chunking — Token Count Consistency
- `_make_chunk()` now uses tiktoken encoder for accurate `token_count` field.
- `_chunk_hybrid()` merges tiny first chunks FORWARD (not just backward) to
  avoid tiny leading fragments when first sentence boundary is early.

---

## All Milestones Complete ✅ + Phase 4 & 4b Improvements Applied

**Final state**: `pytest tests/ -q` → 84 passed in 0.24s

### Phase 4 improvements (Session 3)
- **8K LLM token budget** (configurable in `config/default.yaml`)
- **Full transcript saved** as `transcript.txt` alongside notes
- **Smart frame capture**: scene change + transition-aware + content scoring + dedup
- **Multiple frames per section** via `get_frames_in_range()`
- **`run.sh`** wrapper script for easy usage
- **`glow`** installed for terminal markdown viewing

### Phase 4b improvements (Session 3 continued)
- **Executive summary**: LLM-generated overview + key highlights before detailed sections
- **Inline frames**: Interleaved between key_points by timestamp (not dumped at end)
- **Video clip embedding**: Local MP4 clips per section via ffmpeg stream copy
- **Separate `transcript.md`**: Full transcript with blurb-style grouping + inline frames
- **Robust LLM scoring**: Handles verbose/thinking model responses, `detail=high` keeps all chunks
- **Obsidian integration**: `view.sh` interactive browser, proper anchor links
- **No YouTube links**: All content references are local

### Output structure
```
output/<video>/
├── notes.md          ← notes + inline frames + clips + exec summary
├── transcript.md     ← full transcript in blurbs + inline frames + clips
├── transcript.txt    ← plain text transcript
├── metadata.json
├── frames/           ← extracted frame images
└── clips/            ← section video clips
```

### Quick start
```bash
./run.sh 'https://www.youtube.com/watch?v=VIDEO_ID'
./view.sh                                    # interactive output browser
./view.sh neural_network                     # direct folder lookup
glow output/Video_Title_ID/notes.md          # terminal preview
```

### Potential future work
- Test with `--mode=api` (Anthropic) — needs `ANTHROPIC_API_KEY` set
- Test LMStudio provider when LMStudio is running locally
- Longer video test (30+ min) to validate chunking at scale
- Consider `insightforge batch` command for processing multiple URLs
