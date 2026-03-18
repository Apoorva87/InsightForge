# InsightForge Execution Log

Chronological record of what has been done, what was found, and what changed.
Most recent entry at the top.

---

## 2026-03-17 — Session 3 (continued): Phase 4b — Output Quality & UX

### Changes implemented
1. **LLM scoring fix**: Simplified scoring prompt to "Reply with ONLY a number between 0.0 and 1.0". `_parse_score()` now never raises — defaults to 0.5 on unparseable text. Handles verbose GLM assessments gracefully.
2. **`detail=high` keeps ALL chunks**: Changed from threshold-based filtering to keeping everything. Scores only used in `detail=low` for top quartile selection.
3. **Executive summary**: LLM-generated overview with key highlights, placed before detailed sections in notes.md. Fallback builds summary from section headings when LLM fails.
4. **Inline frames**: Frames interleaved between key_points based on timestamp alignment (divides section time range into equal slots per point, inserts frames after each slot). No more frame dumps at section end.
5. **Video clip embedding**: Local MP4 clips per section cut from downloaded video via `ffmpeg -ss START -i video -to DURATION -c copy`. `<video controls>` tags in notes.md and transcript.md.
6. **Separate `transcript.md`**: Full raw transcript with inline frames and clips per section. Removed collapsible transcript from notes.md.
7. **Blurb-style transcript**: Segments grouped at frame boundaries. One bold timestamp per blurb, continuous paragraph text, then frame images. No per-sentence timestamps.
8. **Obsidian anchor fix**: `_heading_to_anchor()` only strips `#[](){}|\^`` chars, keeps commas/periods (Obsidian keeps these unlike GitHub).
9. **Removed YouTube links**: No more YouTube timestamp links anywhere — all references are local.
10. **Installed Obsidian** (v1.12.4) at `/Applications/Obsidian.app`
11. **`view.sh`**: Interactive output browser with glow/obsidian/transcript/finder modes. Direct folder lookup via `./view.sh neural_network`.

### Bugs found and fixed
- **GLM verbose scoring**: Model returned "Assessment: This chunk introduces..." instead of a number. Fixed with simplified prompt + robust parsing.
- **Too few chunks retained**: Even with threshold 0.15, only 3/6 chunks passed. Fixed by making `detail=high` keep ALL chunks.
- **Obsidian anchor links broken**: `_heading_to_anchor` stripped commas but Obsidian keeps them. Fixed regex to only strip `#[](){}|\^`` chars.
- **Transition frames in wrong dir**: `frames.py` extracted to subfolder. Fixed to use `tr_` prefix in same dir.
- **Obsidian vault not found** (multiple iterations): URI schemes failed for unregistered vaults. Final fix: `open -a Obsidian "$VAULT_DIR"` with per-video output folders as vaults.

### Files modified
- `insightforge/stages/formatter.py` — Major rewrite: inline frames, exec summary, transcript.md generation, blurb grouping, no YouTube links
- `insightforge/stages/importance.py` — Simplified scoring prompt, robust `_parse_score()`, `detail=high` keeps all
- `insightforge/stages/llm_processing.py` — Executive summary generation (`generate_executive_summary()`)
- `insightforge/stages/frames.py` — Transition frame directory fix
- `insightforge/models/output.py` — Added `executive_summary`, `transcript_md_content`, `clips_dir`, `timestamp_end_str`
- `insightforge/llm/ollama_provider.py` — `_extract_from_thinking()` finds note-section JSON in thinking traces
- `insightforge/utils/ffmpeg.py` — `cut_video_clips()` for section clip cutting
- `insightforge/pipeline.py` — Stages 7b (exec summary), 7c (clip cutting), updated stage 8 args
- `insightforge/storage/writer.py` — Writes `transcript.md` and `clips/` directory
- `insightforge/storage/paths.py` — Added `clips_dir()`
- `config/default.yaml` — `importance.threshold: 0.15`
- `tests/unit/test_formatter.py` — Updated anchor test for Obsidian format
- `view.sh` — New interactive output browser
- `run.sh` — Made executable

### Demo output (neural network video, 18:40)
- 6 sections, 36 frames, 6 video clips
- Executive summary with key highlights
- Inline frames interleaved with key points
- Separate transcript.md with blurb-style text + frames
- 84/84 tests passing

### Output structure
```
output/<video>/
├── notes.md          ← summarized notes + inline frames + clips + exec summary
├── transcript.md     ← full raw transcript in blurbs + inline frames + clips
├── transcript.txt    ← plain text transcript
├── metadata.json
├── frames/           ← extracted frame images
└── clips/            ← section video clips
```

---

## 2026-03-17 — Session 3: Phase 4 Improvements

### Changes implemented
1. **LLM token budget → 8192** (configurable via `config/default.yaml` → `llm_processing.max_tokens`)
2. **Full transcript preservation**: `transcript.txt` written alongside `notes.md` with all timestamped segments
3. **Smart frame capture**: transition-aware extraction at chunk boundaries + scene changes, content scoring via JPEG file size, deduplication by proximity
4. **More frames per section**: `get_frames_in_range()` attaches ALL frames within time window (was: 1 nearest frame)
5. **Better fallback sections**: extract sentences instead of raw transcript dump
6. **`run.sh` wrapper**: auto-detects Python 3.11, passes args through, colorized output
7. **Installed `glow` (v2.1.1)** for terminal markdown viewing

### Bugs found and fixed
- **Transition frames in subfolder**: `frames.py` extracted transition frames to `output_dir/transitions/` causing broken image refs in notes.md. Fix: extract into same dir with `tr_` prefix.
- **Frames not sorted by timestamp in notes**: `get_frames_in_range()` sorted by content_score. Fix: formatter now sorts frames by timestamp for chronological display.
- **`extract_frames_at_timestamps` filename collisions**: Added `prefix` parameter to avoid `ts_` collisions between primary and transition extractions.

### Files modified (9 files)
- `insightforge/models/frame.py` — added `content_score`, `get_frames_in_range()`
- `insightforge/models/output.py` — added `transcript_path`
- `insightforge/stages/llm_processing.py` — 8K tokens, multi-frame, better fallback
- `insightforge/stages/frames.py` — transition-aware + content scoring + dedup
- `insightforge/stages/formatter.py` — sort frames by timestamp
- `insightforge/storage/paths.py` — added `transcript_path()`
- `insightforge/storage/writer.py` — writes `transcript.txt`
- `insightforge/pipeline.py` — passes transcript and max_tokens config
- `insightforge/utils/ffmpeg.py` — `prefix` parameter on `extract_frames_at_timestamps`
- `config/default.yaml` — `llm_processing.max_tokens: 8192`, `scene_diff_threshold: 0.2`, `top_k: 30`
- `run.sh` — new wrapper script

### Demo output (Python in 100 Seconds)
- 14 frames (12 scene changes + 3 transition, 1 deduped) — up from 8 in previous run
- All frames sorted chronologically in notes.md with valid relative paths
- Full transcript: 30 segments, 458 words in `transcript.txt`
- 84/84 tests passing

---

## 2026-03-17 — Session 2: M3–M7 complete, M8 next

### Milestones completed this session
- ✅ M3: Ingestion + Transcript (stages 1–3) — validated live
- ✅ M4: Chunking + Importance (stages 4 + 6) — validated live with Ollama
- ✅ M5: Visual Frame Pipeline (stage 5 + ffmpeg.py) — validated live
- ✅ M6: LLM Processing + Output (stages 7 + 8) — validated live
- ✅ M7: Storage + Pipeline — full `pipeline.run()` E2E tested

### Bugs found and fixed

#### M3 — ffmpeg required for yt-dlp format merging
- `yt-dlp` format selector `bestvideo+bestaudio` requires ffmpeg to merge streams.
- Without ffmpeg it throws `DownloadError` immediately.
- **Fix**: installed ffmpeg via `brew install ffmpeg` (now `/opt/homebrew/bin/ffmpeg` v8.0.1).
- Also added `"noprogress": True` to `_build_ydl_opts` to suppress download spam.

#### M4 — Chunking: small first chunk not merged forward
- `_chunk_hybrid` only merged small chunks into previous neighbor.
- If the very first chunk was < min_tokens (e.g. 44 tokens), it stayed as a tiny orphan.
- **Fix**: added a second pass in `_chunk_hybrid` that merges small FIRST chunks forward
  into the second chunk. Added `_merge_chunks()` helper to DRY up the merge logic.

#### M4 — Chunking: token_count used word-split instead of tiktoken
- `_make_chunk()` used `len(text.split())` for token_count, but budget checking used
  tiktoken. Mismatch caused reported token counts to differ from actual.
- **Fix**: `_make_chunk()` now accepts `encode` parameter and uses it when provided.
  All call sites updated to pass the encoder.

#### M4 — Importance scoring: GLM-4.7-flash is a thinking model
- `glm-4.7-flash:latest` is the only available text model in Ollama.
- It's a reasoning/thinking model that puts chain-of-thought in Ollama's `thinking`
  response field and actual output in `response`.
- With `max_tokens=32`, all budget went to thinking → empty `response`.
- With `max_tokens=256+`, thinking expanded to fill the budget → still empty.
- **512 tokens** is the sweet spot: thinking completes and response is produced.
- **Fix 1**: `OllamaProvider.complete()` now extracts answer from `thinking` when
  `response` is empty via `_extract_from_thinking()` helper.
- **Fix 2**: `_extract_from_thinking()` uses regex to find last valid JSON with numeric
  score, score patterns, or bare floats — skipping template strings like
  `{"score": <float 0.0-1.0>}` that get picked up from prompts.
- **Fix 3**: Updated both scoring and note-generation prompts to remove template
  placeholders that the model could latch onto.
- **Fix 4**: `_score_chunk_llm()` in importance.py now uses 512 token budget.
  `_generate_section()` in llm_processing.py uses 1024 tokens (more output needed).
- **Fix 5**: Added `_parse_score()` helper that handles: JSON, bare float, quoted float,
  and prose-embedded numbers including 0–10 scale normalisation.

#### M5 — ffmpeg scene change: exit code 234 on low-motion video
- Short/static videos (e.g. 19s zoo clip) have no scene changes above 0.2 threshold.
- ffmpeg exits with code 234 ("nothing was written") when select filter returns 0 frames.
- **Fix**: `extract_frames_scene_change()` now catches `FFmpegError` on empty result
  and falls back to `extract_frames_interval()` with 30s interval.
- Also fixed filter quoting: `select=gt(scene\\,{threshold})` (escaped comma) instead
  of `select='gt(scene,{threshold})'` (shell quoting that caused issues).

### Model config update
- Changed `config/default.yaml` Ollama model from `llama3.2` (not installed) to
  `glm-4.7-flash:latest` (the only available text model).

### Test results
```
python3.11 -m pytest tests/ -q
84 passed in 0.24s   (+ 1 warning for unregistered pytest marker)
```
Added `markers` to `pyproject.toml` to register `integration` mark.

### E2E validation
```
pipeline.run(VideoJob(url='https://www.youtube.com/watch?v=x7X9w_GIm1s'))
```
Output: `pipeline_output/Python_in_100_Seconds_x7X9w_GIm1s/`
- `notes.md` ✅
- `metadata.json` ✅
- `frames/` (8 scene change frames) ✅

---

## 2026-03-17 — Session 1: Full scaffold + M1 + M2 complete

### What happened
- **Plan finalized** in plan mode: 9-stage pipeline, Pydantic contracts, LLMProvider ABC,
  concurrent fork at stages 5+6, `faster-whisper`, Ollama/LMStudio/Anthropic providers.
- **Full scaffold created** in one pass:
  - 50+ files across `insightforge/`, `tests/`, `config/`, root config files
  - All Python modules: models, stages, llm, storage, utils, cli, pipeline
  - All unit test files with `conftest.py` fixture factories
  - Integration smoke test (stages 3–9, no external I/O)
  - `config/default.yaml`, `.gitignore`, `.env.example`, `pyproject.toml`
  - Full `README.md`

### Tests run
```
python3.11 -m pytest tests/unit/ -q
83 passed in 0.22s
```

### Bugs fixed during session
- `tests/unit/test_transcript.py::test_parses_valid_api_response`: `_try_youtube_transcript`
  uses a local import so `patch()` on the module attribute fails. Fixed by patching
  `sys.modules` with a full mock module object.

### Milestone assessment at end of session
- **M1 COMPLETE**: All models, config loader, logging setup.
- **M2 COMPLETE**: LLMProvider ABC + 3 providers + LLMRouter.
- **M3–M8**: Scaffold code written with real logic, NOT yet validated live.

---

## 2026-03-17 — Session 2 continued: M8 complete

### M8 — CLI + Integration

- `insightforge check`: all 7 dependencies now show **OK** (ffmpeg installed this session)
- `insightforge process https://www.youtube.com/watch?v=x7X9w_GIm1s --output-dir ./cli_output`:
  - All 9 stages executed successfully
  - `notes.md`, `frames/` (8 images), `metadata.json` written
- Added `integration` pytest marker to `pyproject.toml` to suppress warning
- Final test run: **84 passed in 0.25s** ✅

### All milestones complete as of this session.
