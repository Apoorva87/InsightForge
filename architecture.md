# InsightForge Architecture

This document describes the internal architecture of InsightForge — a local-first YouTube Knowledge Extractor that converts video URLs into structured Markdown notes with embedded timestamped screenshots and optional audio summaries.

---

## System Overview

```
┌───────────────────────────────────────────────────────────────────┐
│                         CLI (cli.py)                              │
│   insightforge process <url> --mode --detail --frames --audio     │
└───────────────────────┬───────────────────────────────────────────┘
                        │  VideoJob
                        ▼
┌───────────────────────────────────────────────────────────────────┐
│                    Pipeline Orchestrator                           │
│                      (pipeline.py)                                 │
│                                                                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│  │ Stage 1  │→│ Stage 2  │→│ Stage 3  │→│ Stage 4  │             │
│  │Ingestion │ │Transcript│ │Alignment │ │ Chunking │             │
│  └──────────┘ └──────────┘ └──────────┘ └────┬─────┘             │
│                                               │                   │
│                                    ┌──────────┴──────────┐        │
│                                    │  ThreadPoolExecutor  │        │
│                                    │    (max_workers=2)   │        │
│                                    ├──────────┬──────────┤        │
│                                    ▼          ▼          │        │
│                              ┌──────────┐ ┌──────────┐  │        │
│                              │ Stage 5  │ │ Stage 6  │  │        │
│                              │  Frames  │ │Importance│  │        │
│                              └────┬─────┘ └────┬─────┘  │        │
│                                   └──────┬─────┘        │        │
│                                          ▼              │        │
│                                   ┌──────────┐          │        │
│                                   │ Stage 7  │          │        │
│                                   │   LLM    │          │        │
│                                   │Processing│          │        │
│                                   └────┬─────┘          │        │
│                                        │                │        │
│                            ┌───────────┼───────────┐    │        │
│                            ▼           ▼           ▼    │        │
│                      ┌──────────┐ ┌──────────┐ ┌──────┐│        │
│                      │Stage 7b  │ │Stage 7c  │ │Stage ││        │
│                      │Exec Summ.│ │Clip Cut  │ │ 7d   ││        │
│                      └────┬─────┘ └────┬─────┘ │Audio ││        │
│                           └──────┬─────┘       └──┬───┘│        │
│                                  ▼                │    │        │
│                           ┌──────────┐            │    │        │
│                           │ Stage 8  │◄───────────┘    │        │
│                           │Formatter │                  │        │
│                           └────┬─────┘                  │        │
│                                ▼                        │        │
│                           ┌──────────┐                  │        │
│                           │ Stage 9  │                  │        │
│                           │ Storage  │                  │        │
│                           └──────────┘                  │        │
└───────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Stages

### Stage 1: Ingestion (`stages/ingestion.py`)

**Input:** `VideoJob` (URL, options)
**Output:** `VideoMetadata` + video file path

Downloads video and metadata using `yt-dlp`. Extracts title, channel, duration, upload date, description, and thumbnail URL. Creates a temporary working directory for intermediate artefacts.

Key behaviours:
- Format selector `bestvideo+bestaudio` merges via ffmpeg
- Metadata parsed from yt-dlp's `info_dict`
- Working directory created under system temp with UUID prefix

### Stage 2: Transcript (`stages/transcript.py`)

**Input:** `VideoMetadata`, video path
**Output:** `TranscriptResult` (raw segments)

Obtains a timestamped transcript via one of two sources:

| Priority | Source | When Used |
|----------|--------|-----------|
| 1 | YouTube manual/auto captions | `prefer_manual=True` and captions available |
| 2 | `faster-whisper` local model | Captions unavailable or `prefer_manual=False` |

Each segment contains `start`, `end`, `text`, and optional `confidence` score.

### Stage 3: Alignment (`stages/alignment.py`)

**Input:** `TranscriptResult` (raw)
**Output:** `TranscriptResult` (cleaned, aligned)

Cleans and normalises transcript segments:
- Removes duplicate/overlapping segments
- Fills time gaps (> 0.5s) between segments
- Trims leading/trailing whitespace
- Sets `is_aligned = True`

### Stage 4: Chunking (`stages/chunking.py`)

**Input:** `TranscriptResult`
**Output:** `ChunkBatch`

Splits transcript into token-bounded, semantically coherent chunks. Three strategies:

| Strategy | Description |
|----------|-------------|
| `token` | Fixed token windows with overlap |
| `sentence` | Split at sentence boundaries (NLTK) |
| `hybrid` (default) | Sentence-aware splits within token budgets |

Key parameters: `max_tokens` (800), `min_tokens` (100), `overlap_tokens` (50). Token counting uses `tiktoken` for accuracy.

Small leading chunks are merged forward to avoid tiny fragments.

### Stage 5: Frame Extraction (`stages/frames.py`) — *concurrent*

**Input:** Video path, `ChunkBatch`
**Output:** `FrameSet`

Runs concurrently with Stage 6 via `ThreadPoolExecutor`.

Extraction pipeline:
1. **Primary extraction** — scene change detection (`gt(scene,threshold)`), fixed interval, or timestamp-aligned
2. **Transition supplements** — additional frames at chunk boundaries (topic changes)
3. **Deduplication** — frames within 3s of each other merged, keeping the larger file
4. **Content scoring** — JPEG file size as proxy for visual richness (text/diagrams compress larger)
5. **Top-K selection** — keep the K most content-rich frames

Falls back to interval extraction if scene change detection produces zero frames (common with static/talking-head videos).

### Stage 6: Importance Scoring (`stages/importance.py`) — *concurrent*

**Input:** `ChunkBatch`, LLM provider, optional `FrameSet`
**Output:** `list[ScoredChunk]`

Runs concurrently with Stage 5.

Each chunk receives:
- **LLM score** (0.0–1.0): semantic importance rated by the LLM
- **Visual score** (0.0–1.0): scene change magnitude from nearest frame
- **Composite score**: `llm_weight × llm_score + visual_weight × visual_score`

Filtering by `--detail`:
- `high` — keeps ALL chunks (scores used for ordering only)
- `low` — keeps top quartile of chunks above threshold

### Stage 7: LLM Processing (`stages/llm_processing.py`)

**Input:** `list[ScoredChunk]`, `FrameSet`, LLM provider
**Output:** `list[NoteSection]`

For each scored chunk, the LLM generates:
- A section **heading**
- A **summary** paragraph
- 3–5 **key points** (bullet points)

Response format is JSON, parsed with fallback handling for thinking models that embed answers in chain-of-thought traces.

Frames are attached to sections via `get_frames_in_range()` using the chunk's time window.

### Stage 7b: Executive Summary

**Input:** `list[NoteSection]`, LLM provider
**Output:** Summary string

Generates a 2–4 sentence overview + 3–5 key highlights from all section summaries. Falls back to a deterministic summary built from section headings if LLM fails.

### Stage 7c: Video Clip Cutting

**Input:** Video path, section time ranges
**Output:** MP4 clips in work directory

Uses `ffmpeg -c copy` (stream copy — no re-encoding) to cut the video into one clip per section. Fast and lossless.

### Stage 7d: Audio Summary (optional)

**Input:** Transcript text, executive summary, `--audio` verbosity level
**Output:** MP3/AIFF audio file

Generates a text-to-speech audio file with controllable verbosity:
- `0.0` — executive summary only (shortest)
- `1.0` — full transcript (longest)
- `0.5` — section summaries (middle ground)

Uses macOS `say` command with `ffmpeg` conversion, or `pyttsx3` as cross-platform fallback.

### Stage 8: Formatter (`stages/formatter.py`)

**Input:** `list[NoteSection]`, metadata, frames, clips, transcript, executive summary
**Output:** `FinalOutput` (rendered Markdown strings)

Assembles two Markdown documents:

**`notes.md`** — structured notes:
- Header (title, channel, duration, upload date)
- Table of contents with timestamps
- Executive summary with key highlights
- Sections with inline frames interleaved between key points
- Embedded `<video>` tags for local clip playback

**`transcript.md`** — full transcript:
- Same header and table of contents
- Full raw transcript grouped into "blurbs" (continuous text between frame positions)
- One timestamp per blurb, not per sentence
- Inline frames at natural break points

### Stage 9: Storage (`storage/writer.py`)

**Input:** `FinalOutput`, metadata, transcript
**Output:** Files on disk

Writes the final artefact bundle:

```
output/<Title>_<VideoID>/
├── notes.md              ← structured notes
├── transcript.md         ← full transcript with frames
├── transcript.txt        ← plain text transcript
├── metadata.json         ← machine-readable metadata
├── summary.mp3           ← audio summary (if --audio used)
├── frames/               ← extracted JPEG screenshots
│   ├── scene_000001.jpg
│   ├── tr_000001.jpg     ← transition frames
│   └── ...
└── clips/                ← section video clips
    ├── section_0000.mp4
    └── ...
```

Optionally cleans up the temporary working directory after copying artefacts.

---

## Data Models

All stage boundaries use Pydantic models for type safety, validation, and serialisation.

```
models/
├── video.py       VideoJob, VideoMetadata
├── transcript.py  TranscriptSegment, TranscriptResult
├── chunk.py       Chunk, ChunkBatch
├── frame.py       Frame, FrameSet
├── scoring.py     ScoredChunk
└── output.py      NoteSection, FinalOutput
```

### Data Flow

```
VideoJob ──┐
           ▼
     VideoMetadata ──┐
                     ▼
              TranscriptResult (raw) ──┐
                                       ▼
                                TranscriptResult (aligned) ──┐
                                                             ▼
                                                       ChunkBatch
                                                        ╱       ╲
                                                FrameSet    list[ScoredChunk]
                                                        ╲       ╱
                                                     list[NoteSection]
                                                            │
                                                       FinalOutput
```

### Key Model Relationships

| Model | Key Fields | Produced By |
|-------|-----------|-------------|
| `VideoJob` | url, mode, detail, frames_enabled, audio_level | CLI input |
| `VideoMetadata` | video_id, title, channel, duration_seconds, work_dir | Stage 1 |
| `TranscriptSegment` | start, end, text, confidence | Stage 2 |
| `TranscriptResult` | segments[], source, language, word_count, is_aligned | Stage 2–3 |
| `Chunk` | chunk_id, text, start, end, token_count | Stage 4 |
| `ChunkBatch` | chunks[], strategy, total_tokens | Stage 4 |
| `Frame` | frame_id, timestamp, path, content_score | Stage 5 |
| `FrameSet` | frames[], extraction_mode, frames_dir | Stage 5 |
| `ScoredChunk` | chunk, llm_score, visual_score, composite_score | Stage 6 |
| `NoteSection` | section_id, heading, summary, key_points, frames[] | Stage 7 |
| `FinalOutput` | sections[], markdown_content, transcript_md_content, paths | Stage 8 |

---

## LLM Abstraction Layer

```
llm/
├── base.py              LLMProvider (ABC), LLMRequest, LLMResponse
├── ollama_provider.py   OllamaProvider — httpx to /api/generate
├── openai_provider.py   OpenAIProvider — OpenAI SDK (also LMStudio)
├── anthropic_provider.py AnthropicProvider — Anthropic SDK
└── router.py            LLMRouter — ordered fallback chain
```

### LLMProvider Interface

```python
class LLMProvider(ABC):
    @property
    def name(self) -> str: ...
    def complete(self, request: LLMRequest) -> LLMResponse: ...
    def is_available(self) -> bool: ...
```

All pipeline stages interact only with the `LLMProvider` interface. The `LLMRouter` selects and falls back between concrete providers:

| Mode | Provider Chain |
|------|---------------|
| `local` | Ollama → LMStudio (OpenAI-compatible) |
| `api` | Anthropic |

### Thinking Model Support

Some local models (e.g., GLM-4.7-flash) are "thinking" models that place chain-of-thought in a separate `thinking` field. `OllamaProvider` detects empty `response` with non-empty `thinking` and extracts the answer via `_extract_from_thinking()`:

1. Find all JSON objects in the thinking trace
2. Prefer larger objects containing `heading`/`summary` (note sections)
3. Fall back to objects containing `score` (importance scoring)
4. Last resort: use the last JSON object found

---

## Concurrency Model

Stages 5 (frame extraction) and 6 (importance scoring) run concurrently:

```python
with ThreadPoolExecutor(max_workers=2) as executor:
    futures["frames"] = executor.submit(frames_stage.run, ...)      # I/O-bound
    futures["importance"] = executor.submit(importance.run, ...)     # network-bound
```

This works because:
- Frame extraction is **I/O-bound** (ffmpeg subprocess, disk writes)
- Importance scoring is **network-bound** (LLM API calls)
- They share no mutable state (different inputs, no data dependencies)

All other stages are sequential — each depends on the previous stage's output.

---

## Configuration System

```
config/
└── default.yaml          ← base configuration
```

Configuration is loaded by `utils/config.py` with three layers of precedence:

1. **`config/default.yaml`** — base defaults
2. **User YAML** (`--config path/to/config.yaml`) — overrides defaults
3. **Environment variables** — highest precedence (`ANTHROPIC_API_KEY`, etc.)

See [`TUNING.md`](TUNING.md) for a complete reference of all configurable parameters and guidance on tuning for different video types.

---

## Storage & Path Management

`storage/paths.py` derives all output paths from the video ID and title:

```python
job_output_dir(base_dir, video_id, title) → base_dir / "Title_videoID"
notes_path(output_dir)                    → output_dir / "notes.md"
transcript_path(output_dir)               → output_dir / "transcript.txt"
frames_dir(output_dir)                    → output_dir / "frames"
clips_dir(output_dir)                     → output_dir / "clips"
metadata_path(output_dir)                 → output_dir / "metadata.json"
audio_path(output_dir)                    → output_dir / "summary.mp3"
```

Titles are sanitised: filesystem-unsafe characters (`<>:"/\|?*`) replaced with underscores, truncated to 60 characters.

---

## Error Handling

The pipeline uses a `PipelineError` exception that wraps stage-specific failures:

```python
class PipelineError(Exception):
    def __init__(self, stage: str, cause: Exception): ...
```

**Fatal stages** (pipeline stops): Ingestion, Transcript, Alignment, Chunking, Importance, LLM Processing, Formatter, Storage.

**Non-fatal stages** (pipeline continues with degraded output):
- Frame extraction — notes produced without images
- Executive summary — notes produced without summary block
- Video clip cutting — notes produced without `<video>` tags
- Audio summary — notes produced without audio file

---

## External Dependencies

| Dependency | Used By | Purpose |
|-----------|---------|---------|
| `yt-dlp` | Stage 1 | Video + metadata download |
| `faster-whisper` | Stage 2 | Local speech-to-text |
| `ffmpeg` | Stage 5, 7c, 7d | Frame extraction, clip cutting, audio conversion |
| `tiktoken` | Stage 4 | Accurate token counting for chunk boundaries |
| `nltk` | Stage 4 | Sentence boundary detection (hybrid chunking) |
| `httpx` | LLM (Ollama) | HTTP client for Ollama API |
| `anthropic` | LLM (API) | Anthropic Claude SDK |
| `openai` | LLM (LMStudio) | OpenAI-compatible SDK |
| `pydantic` | All stages | Data validation and serialisation |
| `typer` + `rich` | CLI | Command-line interface and formatting |
| `pyttsx3` | Stage 7d | Cross-platform text-to-speech (optional) |

---

## File Map

```
insightforge/
├── __init__.py
├── cli.py                  ← Typer CLI entry point
├── pipeline.py             ← 9-stage orchestrator with concurrent fork
├── models/
│   ├── video.py            ← VideoJob (input), VideoMetadata
│   ├── transcript.py       ← TranscriptSegment, TranscriptResult
│   ├── chunk.py            ← Chunk, ChunkBatch
│   ├── frame.py            ← Frame, FrameSet
│   ├── scoring.py          ← ScoredChunk
│   └── output.py           ← NoteSection, FinalOutput
├── stages/
│   ├── ingestion.py        ← [1] yt-dlp download + metadata
│   ├── transcript.py       ← [2] YouTube captions or Whisper
│   ├── alignment.py        ← [3] Clean + gap-fill transcript
│   ├── chunking.py         ← [4] Token-bounded semantic chunking
│   ├── frames.py           ← [5] ffmpeg frame extraction + scoring
│   ├── importance.py       ← [6] LLM + visual importance scoring
│   ├── llm_processing.py   ← [7] Generate NoteSection per chunk
│   └── formatter.py        ← [8] Assemble Markdown documents
├── llm/
│   ├── base.py             ← LLMProvider ABC, LLMRequest, LLMResponse
│   ├── ollama_provider.py  ← Ollama (httpx, thinking model support)
│   ├── openai_provider.py  ← OpenAI-compatible (also LMStudio)
│   ├── anthropic_provider.py ← Anthropic Claude SDK
│   └── router.py           ← LLMRouter with ordered fallback
├── storage/
│   ├── paths.py            ← Output path derivation
│   └── writer.py           ← [9] Write all artefacts to disk
└── utils/
    ├── config.py           ← YAML config loader with merge
    ├── logging.py          ← Rich console or JSON logging
    └── ffmpeg.py           ← Frame, clip, and audio helpers
```
