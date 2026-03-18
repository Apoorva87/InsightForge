# InsightForge Tuning Guide

This guide documents every user-controllable parameter in InsightForge and provides recommendations for tuning output quality across different video types.

---

## Quick Reference: CLI Options

| Flag | Values | Default | Effect |
|------|--------|---------|--------|
| `--mode` | `local`, `api` | `local` | LLM provider: Ollama/LMStudio vs Anthropic |
| `--detail` | `high`, `low` | `high` | How many sections to include |
| `--frames` | `on`, `off` | `on` | Enable/disable frame extraction |
| `--audio` | `0.0`–`1.0` | off | Generate audio summary (0=brief, 1=full transcript) |
| `--model` | model name | from config | Override the LLM model |
| `--output-dir` | path | `./output` | Where to write results |
| `--config` | path | `config/default.yaml` | Custom config file |
| `--verbose` | flag | off | DEBUG-level logging |

---

## Detail Level (`--detail`)

Controls how many transcript chunks make it into the final notes.

### `--detail=high` (default)

- **Keeps ALL chunks** — every part of the video gets a section
- Best for: educational videos, lectures, tutorials where every topic matters
- Produces longer notes with complete coverage

### `--detail=low`

- **Keeps top quartile** — only the most important chunks by composite score
- Chunks below the importance threshold are dropped entirely
- Best for: long videos where you want a highlights summary, or videos with lots of filler (intros, outros, sponsor segments)
- Produces concise notes focused on peak-value content

**When to use `low`:**
- Videos > 30 minutes where you want a quick overview
- Podcast-style content with lots of casual conversation
- Videos with long intros/outros or sponsor segments

---

## Audio Summary (`--audio`)

Generates a text-to-speech audio file from the notes. The value controls verbosity on a 0.0–1.0 scale:

| Value | Content | Typical Length |
|-------|---------|---------------|
| `0.0` | Executive summary only | ~30 seconds |
| `0.3` | Executive summary + section headings | ~1 minute |
| `0.5` | Section summaries (heading + summary paragraph) | ~3–5 minutes |
| `0.7` | Summaries + key bullet points | ~5–10 minutes |
| `1.0` | Full transcript text | Same as video duration |

**Examples:**
```bash
# Quick audio briefing
insightforge process <url> --audio 0.0

# Moderate summary
insightforge process <url> --audio 0.5

# Full transcript as audio
insightforge process <url> --audio 1.0
```

The audio is generated using macOS `say` with ffmpeg conversion to MP3, or `pyttsx3` as a cross-platform fallback. Output is saved as `summary.mp3` in the output directory.

---

## LLM Configuration

### Provider Selection (`llm.mode`)

```yaml
llm:
  mode: local    # "local" or "api"
```

| Mode | Primary Provider | Fallback |
|------|-----------------|----------|
| `local` | Ollama | LMStudio (OpenAI-compatible) |
| `api` | Anthropic Claude | none |

### Ollama Settings

```yaml
llm:
  ollama:
    base_url: http://localhost:11434
    model: glm-4.7-flash:latest
    timeout: 120
    context_window: 8192
```

| Parameter | Effect | Recommendation |
|-----------|--------|----------------|
| `model` | Which Ollama model to use | Use the largest model your GPU can run. `llama3.2` is a good default; `glm-4.7-flash` works but is a thinking model with quirks |
| `timeout` | Seconds before request times out | Increase to 300+ for large models or slow hardware |
| `context_window` | Max tokens the model can see | Match to model's actual context window; 8192 is safe for most |

### Anthropic Settings

```yaml
llm:
  anthropic:
    model: claude-haiku-4-5-20251001
    max_tokens: 4096
```

Requires `ANTHROPIC_API_KEY` environment variable. Haiku is recommended for cost efficiency; Sonnet for higher quality.

### LMStudio Settings

```yaml
llm:
  lmstudio:
    base_url: http://localhost:1234/v1
    model: null    # auto-detected from running server
    timeout: 120
```

LMStudio uses the OpenAI-compatible endpoint. Start LMStudio, load a model, then set `mode: local`. InsightForge tries Ollama first, then LMStudio.

### LLM Processing Token Budget

```yaml
llm_processing:
  max_tokens: 8192
```

Controls the maximum token budget for LLM note generation per chunk. Higher values allow more detailed sections but use more compute.

| Video Type | Recommended |
|-----------|-------------|
| Short (< 5 min) | 4096 |
| Standard (5–30 min) | 8192 |
| Long lectures (30+ min) | 8192–16384 |

---

## Transcript Settings

```yaml
transcript:
  prefer_manual: true
  whisper_model: base
  language: null
```

### `prefer_manual`

When `true`, InsightForge first tries to fetch YouTube's own captions (manual > auto-generated). If unavailable, falls back to local Whisper transcription.

Set to `false` to always use Whisper (useful when YouTube auto-captions are poor quality).

### `whisper_model`

Controls the `faster-whisper` model size:

| Model | VRAM | Speed | Accuracy | Best For |
|-------|------|-------|----------|----------|
| `tiny` | ~1 GB | Fastest | Low | Quick tests, clear English audio |
| `base` | ~1 GB | Fast | Good | Default — good balance |
| `small` | ~2 GB | Moderate | Better | Non-English, accented speakers |
| `medium` | ~5 GB | Slow | High | Important content, noisy audio |
| `large` | ~10 GB | Slowest | Best | Critical accuracy, multi-language |

**Recommendation:** Start with `base`. Upgrade to `small` or `medium` if you notice transcription errors. `large` is rarely needed if YouTube captions are available.

### `language`

Set to an ISO language code (e.g., `"en"`, `"ja"`, `"de"`) to force language detection. Leave as `null` for auto-detection.

Force the language when:
- The video contains multiple languages and you want a specific one
- Auto-detection is picking the wrong language
- The video has very little speech (auto-detect may be unreliable)

---

## Chunking Settings

```yaml
chunking:
  strategy: hybrid
  max_tokens: 800
  min_tokens: 100
  overlap_tokens: 50
```

### `strategy`

| Strategy | Description | Best For |
|----------|-------------|----------|
| `hybrid` (default) | Sentence-aware splits within token budgets | Most videos |
| `sentence` | Split strictly at sentence boundaries | Well-structured lectures |
| `token` | Fixed-size token windows with overlap | When sentences are very long |

### `max_tokens`

Maximum tokens per chunk. Each chunk becomes one section in the notes.

| Value | Effect | Best For |
|-------|--------|----------|
| 400 | More, shorter sections | Dense technical content |
| 800 (default) | Balanced sections | General purpose |
| 1200 | Fewer, longer sections | Narrative/conversational content |
| 2000 | Very few, comprehensive sections | Long-form discussions |

**Key insight:** Smaller `max_tokens` = more sections = more granular notes. Larger = fewer sections = more context per section but less detail.

### `min_tokens`

Minimum chunk size. Chunks smaller than this are merged with neighbours. Increase if you're getting tiny orphan sections.

### `overlap_tokens`

Token overlap between adjacent chunks. Provides context continuity. Higher values improve coherence but increase total LLM calls.

---

## Frame Extraction Settings

```yaml
frames:
  enabled: true
  extraction_mode: scene_change
  interval_seconds: 30.0
  scene_diff_threshold: 0.2
  top_k: 30
  output_quality: 2
  max_width: 1280
```

### `extraction_mode`

| Mode | Description | Best For |
|------|-------------|----------|
| `scene_change` (default) | Detects visual transitions | Slide presentations, tutorials with visuals |
| `interval` | Fixed time interval | Talking-head videos, podcasts |
| `timestamp_aligned` | One frame per chunk midpoint | Guaranteed one frame per section |

### `scene_diff_threshold`

Only applies to `scene_change` mode. Controls sensitivity:

| Value | Sensitivity | Frames Captured | Best For |
|-------|------------|-----------------|----------|
| 0.1 | Very high | Many (50+) | Subtle visual changes |
| 0.2 (default) | High | Moderate (20–40) | General purpose |
| 0.3 | Medium | Fewer (10–20) | Slide presentations |
| 0.5 | Low | Very few (5–10) | Only major scene changes |

**Tip:** If you're getting too many similar frames, increase the threshold. If important visuals are being missed, decrease it.

If scene change detection produces zero frames (common with static videos), InsightForge automatically falls back to `interval` mode.

### `interval_seconds`

Time between frames in `interval` mode, and the fallback interval when scene change detection finds nothing.

| Value | Effect |
|-------|--------|
| 15 | Frame every 15s — lots of frames |
| 30 (default) | Frame every 30s — balanced |
| 60 | Frame every minute — sparse |

### `top_k`

Maximum number of frames to keep after scoring and deduplication.

| Video Length | Recommended `top_k` |
|-------------|-------------------|
| < 5 min | 10–15 |
| 5–20 min | 20–30 |
| 20–60 min | 30–50 |
| 60+ min | 50–80 |

### `output_quality`

JPEG quality for extracted frames (ffmpeg `-q:v` parameter):

| Value | Quality | File Size |
|-------|---------|-----------|
| 1 | Best | Largest |
| 2 (default) | Very good | Good balance |
| 5 | Good | Smaller |
| 10 | Acceptable | Much smaller |

### `max_width`

Maximum frame width in pixels. Height scales proportionally. Reduce for smaller output sizes.

---

## Importance Scoring Settings

```yaml
importance:
  threshold: 0.15
  llm_weight: 0.7
  visual_weight: 0.3
  batch_size: 5
```

### `threshold`

Minimum composite score for a chunk to be considered "important". Only affects `--detail=low` mode (in `high` mode, all chunks are kept regardless).

| Value | Effect |
|-------|--------|
| 0.1 | Keep almost everything |
| 0.15 (default) | Keep most content, filter obvious filler |
| 0.3 | Moderate filtering |
| 0.5 | Aggressive — only high-value content |

### `llm_weight` and `visual_weight`

Control the balance between semantic (LLM) and visual (frame) importance signals:

```
composite_score = llm_weight × llm_score + visual_weight × visual_score
```

| Scenario | `llm_weight` | `visual_weight` |
|----------|-------------|-----------------|
| Default | 0.7 | 0.3 |
| Mostly visual (slides, demos) | 0.4 | 0.6 |
| Mostly audio (podcast, lecture) | 0.9 | 0.1 |
| Balanced | 0.5 | 0.5 |

---

## Output Settings

```yaml
output:
  base_dir: ./output
  embed_frames_inline: true
  include_timestamp_index: true
  markdown_flavor: github
```

### `embed_frames_inline`

When `true`, frames are interleaved between key points in the notes based on timestamp alignment. When `false`, frames are listed at the end of each section.

### `include_timestamp_index`

When `true`, generates a clickable table of contents at the top of notes.md with timestamps and anchor links.

### `markdown_flavor`

Currently supports `github` (default). Affects anchor link generation and HTML tag usage.

---

## Logging Settings

```yaml
logging:
  level: INFO
  format: text
```

| Level | Output |
|-------|--------|
| `DEBUG` | Everything — including LLM prompts/responses, ffmpeg commands |
| `INFO` (default) | Stage progress, frame counts, section counts |
| `WARNING` | Only problems and fallbacks |
| `ERROR` | Only failures |

Set `format: json` for structured log output (useful for piping to log aggregators).

---

## Video Type Recipes

### Slide Presentation / Technical Talk

```yaml
frames:
  extraction_mode: scene_change
  scene_diff_threshold: 0.15    # catch every slide change
  top_k: 50
chunking:
  max_tokens: 600               # more granular sections
importance:
  visual_weight: 0.5            # visuals are important
```

```bash
insightforge process <url> --detail=high
```

### Talking Head / Podcast

```yaml
frames:
  extraction_mode: interval
  interval_seconds: 60           # one frame per minute is enough
  top_k: 15
chunking:
  max_tokens: 1200               # fewer, longer sections
importance:
  llm_weight: 0.9
  visual_weight: 0.1             # visuals don't matter much
```

```bash
insightforge process <url> --detail=low --audio 0.5
```

### Coding Tutorial / Demo

```yaml
frames:
  extraction_mode: scene_change
  scene_diff_threshold: 0.1      # catch code changes on screen
  top_k: 40
chunking:
  max_tokens: 800
importance:
  visual_weight: 0.6             # code on screen is high value
```

```bash
insightforge process <url> --detail=high
```

### Long Lecture (60+ minutes)

```yaml
chunking:
  max_tokens: 1000               # bigger chunks for overview
  overlap_tokens: 80
frames:
  top_k: 60
  scene_diff_threshold: 0.25
transcript:
  whisper_model: small            # better accuracy for long content
```

```bash
insightforge process <url> --detail=high --audio 0.5
```

### Quick Summary / Highlights Only

```yaml
chunking:
  max_tokens: 1200               # big chunks
importance:
  threshold: 0.4                 # aggressive filtering
```

```bash
insightforge process <url> --detail=low --frames=off --audio 0.0
```

---

## Storage Settings

```yaml
storage:
  cleanup_work_dir: true
```

When `true`, deletes the temporary working directory (downloaded video, intermediate frames) after writing final output. Set to `false` to keep the raw downloaded video for debugging or re-processing.

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Required for `--mode=api` |
| `OPENAI_API_KEY` | Required if using OpenAI cloud (not needed for LMStudio) |

---

## Performance Tips

1. **GPU acceleration**: Ensure Ollama is using your GPU (`ollama run <model>` should show GPU layers). This is the single biggest performance factor.

2. **Whisper model size**: `base` is 10x faster than `large` with 90% of the accuracy. Only upgrade if transcript quality is poor.

3. **Frame extraction**: `scene_change` mode is faster than `interval` for most videos because it produces fewer frames.

4. **Token budget**: Lower `llm_processing.max_tokens` if LLM responses are slow. The LLM rarely needs the full budget.

5. **Skip frames**: Use `--frames=off` if you don't need screenshots — saves significant processing time.

6. **Cleanup**: Keep `storage.cleanup_work_dir: true` to avoid accumulating downloaded videos (which can be several GB each).
