# InsightForge — Performance Improvements

Ranked by estimated time savings. All items are now implemented.

---

## 1. Whisper Transcription (biggest bottleneck for long videos)

**Problem**: `beam_size=5` + `medium` model on CPU = 30+ minutes for a 60-min video. No progress output after "Detected language" — appears hung.

**Fixes applied** (**DONE**):
- `beam_size=1` (greedy decoding): ~3-5x faster, negligible quality loss for transcription
- `vad_filter=True`: skips silence/non-speech segments — major speedup on lecture-style videos with pauses
- Progress logging every 60s of audio: eliminates "hung" perception

**Estimated savings**: 60-80% of transcription time (e.g., 30 min → 8 min for a 60-min video)

**Further options** (not yet implemented — diminishing returns):
- GPU acceleration: change `device="cpu"` to `device="cuda"` when available (requires CUDA)
- `small` model instead of `medium` for educational: ~2x faster, slightly less technical vocab accuracy
- Batched inference with `batched=True` parameter (faster-whisper ≥0.10)

**Files**: `insightforge/stages/transcript.py`

---

## 2. Parallel LLM Importance Scoring

**Problem**: Each chunk makes a separate blocking LLM call. 40 chunks × 3-5s each = 2-3 minutes.

**Fixes applied** (**DONE**):
- `importance.passthrough()` skips LLM scoring entirely when `detail=high` (all chunks retained anyway) — saves ~80-200s
- `ThreadPoolExecutor(max_workers=4)` for parallel scoring when `detail != high` — ~75% faster
- `parallel_workers` param threaded from pipeline config

**Estimated savings**: 60-75% of scoring time (when scoring is needed)

**Files**: `insightforge/stages/importance.py`, `insightforge/pipeline.py`

---

## 3. Parallel LLM Chunk Summarization (Stage 7)

**Problem**: Leaf-section summaries generated sequentially.

**Status** (**DONE** — already existed):
- `_parallel_map()` with `parallel_workers` threads used for both chunk summary generation and topic section synthesis
- Configured via `llm_processing.parallel_workers` (default: 4)

**Files**: `insightforge/stages/llm_processing.py`

---

## 4. VLM Result Caching (skip per-section reranking)

**Problem**: Each section triggers a separate VLM call to rerank candidate frames. 10+ sections × 2-3s = 15-30s.

**Fixes applied** (**DONE**):
- VLM classification runs once in batch after frame extraction (`_classify_frames_with_vlm`)
- Per-section frame selection now checks if frames are already VLM-classified; if so, uses `content_score` directly instead of making another VLM call
- VLM reranking only fires when frames lack classification (fallback path)

**Estimated savings**: 10-20s (eliminates ~all per-section VLM calls when batch classification succeeds)

**Files**: `insightforge/stages/llm_processing.py`, `insightforge/pipeline.py`

---

## 5. Connection Pooling

**Problem**: `OllamaProvider` created a new `httpx.Client()` per request. TCP handshake overhead on every call.

**Fix applied** (**DONE**):
- `httpx.Client` created once in `__init__` and reused across all requests
- Same client used for `is_available()` health checks

**Estimated savings**: 2-5s total across 50+ calls

**Files**: `insightforge/llm/ollama_provider.py`

---

## 6. Image Base64 Encoding Cache

**Problem**: Same frame image re-encoded to base64 on every VLM call. Frames appear in classification + potentially reranking.

**Fix applied** (**DONE**):
- `@lru_cache(maxsize=256)` on `_image_as_data_url_cached()` keyed by file path
- First encode takes ~5-20ms per image; subsequent lookups are instant

**Estimated savings**: 5-15s depending on frame count and reuse

**Files**: `insightforge/utils/vision.py`

---

## 7. Scene Change Fallback

**Problem**: When scene change detection yields 0 frames, falls back to interval extraction sequentially.

**Status**: Low priority — fallback is already fast (~5s) and only triggers for talking-head videos. Not worth the complexity of parallel extraction.

**Files**: `insightforge/utils/ffmpeg.py`

---

## Summary

| Improvement | Status | Savings |
|-------------|--------|---------|
| Whisper beam_size=1 + VAD | **DONE** | 60-80% of transcription |
| Whisper progress logging | **DONE** | UX (no more "hang") |
| Parallel importance scoring | **DONE** | 60-75% of scoring time |
| Skip importance for detail=high | **DONE** | 80-200s |
| Parallel chunk summarization | **DONE** | (already existed) |
| VLM result caching | **DONE** | 10-20s |
| Connection pooling | **DONE** | 2-5s |
| Image encoding cache | **DONE** | 5-15s |
