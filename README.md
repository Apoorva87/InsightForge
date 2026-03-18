# InsightForge

**Local-first YouTube Knowledge Extractor** — convert any YouTube video into structured Markdown notes with timestamped screenshots, video clips, and optional audio summaries. Runs entirely on your machine via Ollama or LMStudio, with Anthropic Claude as an API fallback.

---

## What It Does

Give InsightForge a YouTube URL and it produces:

- **`notes.md`** — structured notes with executive summary, section headings, key points, and inline screenshots
- **`transcript.md`** — full transcript grouped into readable blurbs with inline frames
- **`transcript.txt`** — plain timestamped transcript
- **`frames/`** — extracted screenshots at scene changes and topic transitions
- **`clips/`** — MP4 video clips, one per section
- **`summary.mp3`** — optional audio summary (controllable verbosity)
- **`metadata.json`** — machine-readable video metadata

```
output/But_what_is_a_neural_network_aircAruvnKk/
├── notes.md
├── transcript.md
├── transcript.txt
├── metadata.json
├── summary.mp3           ← only if --audio is used
├── frames/
│   ├── scene_000001.jpg
│   ├── scene_000002.jpg
│   ├── tr_000001.jpg     ← topic transition frames
│   └── ...
└── clips/
    ├── section_0000.mp4
    ├── section_0001.mp4
    └── ...
```

---

## Prerequisites

| Dependency | Purpose | Required? |
|-----------|---------|-----------|
| **Python 3.10+** | Runtime | Yes |
| **ffmpeg** | Frame extraction, clip cutting, audio conversion | Yes |
| **yt-dlp** | Video download | Yes |
| **Ollama** or **LMStudio** | Local LLM inference | Yes (for `--mode=local`) |
| **Anthropic API key** | Cloud LLM inference | Yes (for `--mode=api`) |

---

## Installation

### 1. Install system dependencies

**macOS:**
```bash
brew install ffmpeg yt-dlp
```

**Ubuntu / Debian:**
```bash
sudo apt update && sudo apt install ffmpeg
pip install yt-dlp
```

### 2. Install a local LLM runtime

**Ollama (recommended):**
```bash
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3.2
```

**LMStudio (alternative):**
Download from [lmstudio.ai](https://lmstudio.ai/), load a model, and start the local server. InsightForge connects via the OpenAI-compatible endpoint at `http://localhost:1234/v1`.

### 3. Install InsightForge

```bash
git clone https://github.com/yourname/insightforge.git
cd insightforge

# Install in editable mode
pip install -e .

# Or with development dependencies (pytest, ruff, mypy)
pip install -e ".[dev]"
```

### 4. Configure environment (optional)

```bash
cp .env.example .env
# Edit .env to add ANTHROPIC_API_KEY if using --mode=api
```

### 5. Verify installation

```bash
insightforge check
```

This checks that ffmpeg, yt-dlp, Ollama, and all Python packages are available.

---

## Quick Start

### Process a video with local LLM

```bash
insightforge process "https://www.youtube.com/watch?v=aircAruvnKk"
```

### Using the convenience wrapper

```bash
# run.sh auto-detects Python 3.11 and provides coloured output
./run.sh "https://www.youtube.com/watch?v=aircAruvnKk"
```

### Browse output interactively

```bash
# Interactive picker with glow/Obsidian viewing options
./view.sh

# Direct lookup by keyword
./view.sh neural_network
```

### More examples

```bash
# Low-detail summary (top quartile of content)
insightforge process "https://www.youtube.com/watch?v=VIDEO_ID" --detail=low

# API mode with Anthropic Claude
insightforge process "https://www.youtube.com/watch?v=VIDEO_ID" --mode=api

# Generate audio summary (0=exec summary, 1=full transcript)
insightforge process "https://www.youtube.com/watch?v=VIDEO_ID" --audio 0.5

# Skip frame extraction for faster processing
insightforge process "https://www.youtube.com/watch?v=VIDEO_ID" --frames=off

# Custom output directory and config
insightforge process "https://www.youtube.com/watch?v=VIDEO_ID" \
  --output-dir=./my-notes \
  --config=./my-config.yaml

# Override the LLM model
insightforge process "https://www.youtube.com/watch?v=VIDEO_ID" --model=llama3.1
```

---

## CLI Reference

```
insightforge process <youtube_url> [OPTIONS]

Arguments:
  youtube_url               YouTube video URL to process

Options:
  --mode, -m TEXT           LLM mode: local | api  [default: local]
  --detail, -d TEXT         Output detail: high | low  [default: high]
  --frames TEXT             Frame extraction: on | off  [default: on]
  --audio FLOAT             Audio summary verbosity: 0.0 (brief) to 1.0 (full)
                            Omit to skip audio generation  [default: off]
  --output-dir, -o PATH    Output directory  [default: ./output]
  --config, -c PATH        Path to config YAML override
  --model TEXT              Override LLM model name
  --verbose, -v             Enable DEBUG logging

insightforge check
  Verify that all required dependencies are installed and reachable.
```

### Detail levels

| `--detail` | Behaviour |
|------------|-----------|
| `high` (default) | Every part of the video gets a section — complete coverage |
| `low` | Only the most important quartile — highlights only |

### Audio verbosity

| `--audio` | Content |
|-----------|---------|
| `0.0` | Executive summary only (~30s) |
| `0.5` | Section summaries (~3–5 min) |
| `1.0` | Full transcript (~video length) |

---

## Configuration

InsightForge uses `config/default.yaml` as its base configuration. Override any setting by passing `--config path/to/custom.yaml`.

Key settings:

```yaml
llm:
  mode: local                         # local | api
  ollama:
    model: llama3.2                   # any model available in Ollama
    timeout: 120
  anthropic:
    model: claude-haiku-4-5-20251001  # requires ANTHROPIC_API_KEY env var

transcript:
  prefer_manual: true                 # use YouTube captions when available
  whisper_model: base                 # tiny | base | small | medium | large

chunking:
  max_tokens: 800                     # tokens per chunk (= section granularity)

frames:
  extraction_mode: scene_change       # scene_change | interval | timestamp_aligned
  scene_diff_threshold: 0.2          # lower = more frames
  top_k: 30                          # max frames to keep
```

For a complete reference of every parameter with tuning guidance for different video types, see **[TUNING.md](TUNING.md)**.

---

## Architecture

InsightForge processes videos through a 9-stage pipeline:

```
YouTube URL
    → [1] Ingestion          download video + metadata
    → [2] Transcript         YouTube captions or local Whisper
    → [3] Alignment          clean + gap-fill transcript
    → [4] Chunking           split into token-bounded sections
              ↓                          ↓
    [5] Frame Extraction    [6] Importance Scoring    ← concurrent
              ↓                          ↓
    → [7] LLM Processing     generate headings, summaries, key points
    → [7b] Executive Summary  overview of the full video
    → [7c] Clip Cutting       one MP4 per section
    → [7d] Audio Summary      TTS of notes (optional)
    → [8] Formatter           assemble Markdown documents
    → [9] Storage             write all artefacts to disk
```

Stages 5 and 6 run concurrently — frame extraction is I/O-bound (ffmpeg) while importance scoring is network-bound (LLM calls).

For the architecture docs covering pipeline flow, storage, HTML viewer internals, AI chat, and logging/debugging, see **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

### LLM providers

| Provider | Mode | Endpoint |
|----------|------|----------|
| Ollama | `local` (primary) | `http://localhost:11434` |
| LMStudio | `local` (fallback) | `http://localhost:1234/v1` |
| Anthropic | `api` | Cloud API |

The `LLMRouter` tries providers in order and falls back automatically on failure.

---

## Viewing Output

### Terminal (glow)

```bash
# Install glow for terminal markdown rendering
brew install glow

glow output/Video_Title_ID/notes.md
```

### Obsidian

```bash
# view.sh can open output in Obsidian with vault registration
./view.sh
# Then select option 2 (Obsidian)
```

### Any Markdown editor

The output is standard GitHub-flavored Markdown. Open `notes.md` or `transcript.md` in any editor that renders Markdown — VS Code, Typora, iA Writer, etc.

---

## Development

```bash
# Run all tests
python3.11 -m pytest tests/ -q

# Run with coverage
pytest tests/unit/ --cov=insightforge --cov-report=term-missing

# Lint
ruff check insightforge/

# Type check
mypy insightforge/
```

### Project structure

```
insightforge/
├── cli.py              ← Typer CLI entry point
├── pipeline.py         ← 9-stage orchestrator with concurrent fork
├── models/             ← Pydantic data contracts (stage boundaries)
├── stages/             ← One module per pipeline stage (1–8)
├── llm/                ← LLMProvider ABC + Ollama/OpenAI/Anthropic + Router
├── storage/            ← File writing and path management (stage 9)
└── utils/              ← Config loader, logging, ffmpeg helpers
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Top-level architecture map with links to storage, viewer, AI chat, and logging deep dives |
| [TUNING.md](TUNING.md) | Complete parameter reference with tuning recipes for different video types |
| [CLAUDE.md](CLAUDE.md) | Development context and session history |
| [execution_log.md](execution_log.md) | Chronological build log |

---

## License

MIT
