# InsightForge — Architecture Improvements for Output Quality & Performance

Ranked by impact on HTML page quality.

---

## 1. Serialize Educational Artifacts to HTML Viewer

**Impact: High | Effort: Low**

`_serialize_section` in `html_export.py` serializes `heading`, `summary`, `key_points`, `frames`, `clip_path`, `subsections` — but **never serializes** `formulas`, `code_snippets`, or `examples`. The JavaScript renderer never sees them. The data is extracted via LLM, stored in `NoteSection`, rendered in markdown... but the HTML viewer drops it entirely.

**Fix:** Add `formulas`, `code_snippets`, and `examples` to the serialized section dict, and render them in the JavaScript `selectSection()` function.

---

## 2. VLM-Augmented Chunk Summaries (Multimodal)

**Impact: Very High | Effort: Medium**

The entire note quality depends on a local model interpreting raw transcript text. But transcripts are lossy — they lose all visual information (what's on slides, diagrams drawn, code shown on screen):

- Formulas are "reconstructed" from speech ("so we have y equals mx plus b") — error-prone
- Code snippets are hallucinated from verbal descriptions — the speaker says "here we define a function" but you never see the actual code
- Diagrams/slides are never described in the notes — the frame is embedded but the text never references what's *in* the frame

**Fix:** When frames exist for a chunk's time range, send the 1-2 best frames *alongside* the transcript text to the chunk summary LLM call. The VLM (qwen3-vl-8b) is already available for reranking — use it for core summarization too. The chunk summary prompt becomes multimodal: transcript text + frame images → structured JSON with accurate formulas, code, diagram descriptions.

---

## 3. Add KaTeX + Markdown Rendering in HTML Viewer

**Impact: High | Effort: Low-Medium**

The HTML viewer has no markdown rendering — `executive_summary` has `**bold**` stripped via regex, formulas aren't rendered as math, code has no syntax highlighting.

**Fix:** Inline a lightweight JS markdown renderer (marked.js, ~8KB) and KaTeX (~30KB). Render summaries and key points as markdown so `**bold**`, `$formula$`, and `` `code` `` display correctly. Small addition that dramatically improves visual quality of educational notes.

---

## 4. VLM-Based Frame Classification (Replace JPEG Heuristic)

**Impact: High | Effort: Medium**

`content_score` is based on JPEG file size — bigger file = more content. This fails for:
- Dark-themed code editors (high entropy, large JPEG, but no educational value beyond the code)
- Animated/busy transitions (large JPEG, zero value)
- Clean whiteboard diagrams on white background (small JPEG, high value)

**Fix:** Run the VLM once on *all* candidate frames in a single batch with a classification prompt ("For each frame, output: slide/diagram/code/talking_head/transition/other and a 0-1 educational value score"). This replaces both the content_score heuristic *and* the per-section reranking — one VLM call instead of N calls. Much faster, much more accurate.

---

## 5. Frame Descriptions from VLM for Better Annotation

**Impact: Medium | Effort: Low**

The `buildAnnotatedPoints` JavaScript function uses Jaccard similarity between tokenized key point text and frame captions. But frame captions are generated from *nearby transcript segments* — they don't describe what's *in* the frame. So you're matching transcript words against transcript words, not matching visual content to textual content.

**Fix:** When the VLM ranks frames, also ask it to output a 1-sentence description of what's visually shown. Store this as `frame.description`. Use this description (not the transcript caption) for frame-to-key-point matching. This makes the annotated view actually meaningful — "this frame shows the backpropagation diagram" matched to "key point: backpropagation computes gradients layer by layer."

---

## 6. Batch LLM Calls for Performance

**Impact: Medium | Effort: Medium**

The pipeline makes ~35+ LLM calls for a 30-min video:
- N chunk importance scoring calls (serial batches of 5)
- N chunk summary calls (parallel, capped at 4 workers)
- T topic synthesis calls (parallel, capped at 4)
- T*S per-section VLM reranking calls (serial within each topic)
- 1 executive summary call

**Fix:**
- Importance scoring: send all chunks in one prompt with structured output (the local model can handle a list of scores)
- VLM reranking: batch all sections' candidates into fewer calls (send 3-4 sections' candidates in one call)
- Skip importance scoring entirely when `detail=high` — all chunks are kept anyway, scores only affect ordering which is already temporal

---

## 7. Upgrade Whisper Model in Educational Mode

**Impact: High for technical content | Effort: Low (config change)**

If you get YouTube auto-captions (not manual), the transcript has no punctuation, wrong word boundaries, and garbled technical terms. Whisper `base` (74M params) is weak on technical vocabulary.

**Fix:** Use `medium` or `large-v3` Whisper when educational mode is active. The quality difference on technical content (math terms, code identifiers, domain jargon) is dramatic. For a tool whose value proposition is accurate notes, this is worth the extra transcription time. Also consider: if YouTube manual captions exist, still run a quick Whisper pass to fill gaps and correct timing — manual captions often have poor timestamp alignment.

---

## 8. Pass Raw Transcript to Topic Synthesis

**Impact: Medium | Effort: Low**

The current flow: raw transcript → chunk summary (compressed) → topic synthesis (from compressed summaries). By the time the topic-level LLM sees the content, it's working from `compact_text` strings like:

```
[02:30-04:15] Neural Networks: Main idea... | Points: point1; point2 | Keywords: ...
```

This is very lossy. The topic synthesis LLM can't produce better notes than the chunk summaries it received. If a chunk summary missed something, it's gone forever.

**Fix:** Pass a truncated version of the raw transcript alongside the compact summaries. The compact summaries serve as a structural guide (headings, transitions), but the raw text preserves detail. With 8K token budgets, there's room for both. For shorter videos (<20 min), consider skipping chunk summaries entirely and synthesizing directly from transcript + frames.

---

## Fundamental Insight

The VLM (qwen3-vl-8b) is available but only used for frame ranking. The highest-leverage redesign is making the VLM a first-class participant in content extraction — not just "which frame is best" but "what does this frame show, and how does it relate to what the speaker is saying." That's what makes educational notes actually educational.
