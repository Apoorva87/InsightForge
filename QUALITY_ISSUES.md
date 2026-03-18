# InsightForge — Quality Issues

Issues that degrade the quality of generated notes, frames, and user comprehension.
These are not crashes — the pipeline runs — but the output could be significantly better.

---

## Q1. Visual scoring uses only chunk midpoint

**Location:** `insightforge/stages/importance.py:180-203`

**Problem:** Each chunk is scored visually based on a single frame near its midpoint.
For long chunks (e.g. 5-10 minutes), the midpoint frame may not represent the chunk's
actual visual content. A chunk that starts with a diagram but ends with a talking head
gets scored only on whatever frame is near its middle.

**Impact:** Chunks with important visuals at the start or end are underscored, so they
may rank lower than they should. The user misses key visual moments.

**Suggested fix:** Sample frames at multiple points (e.g. start, 1/3, midpoint) and
use the maximum visual score across samples.

---

## Q2. Frame interleaving assumes linear time distribution

**Location:** `insightforge/stages/formatter.py:184-221`

**Problem:** `_interleave_frames_with_points()` divides the section's time range into
equal-duration slots (one per key point) and assigns frames to slots by timestamp.
This assumes key points and frames are uniformly distributed over time, which they
rarely are. Key points may cluster at topic transitions; frames may cluster at scene
changes.

**Impact:** Frames can appear next to the wrong key point. A frame showing a diagram
from the second half of a section might be placed after the first key point.

**Suggested fix:** Match each frame to the nearest key point by semantic proximity
or at least by actual timestamp distance to each point's estimated position, rather
than uniform slotting.

---

## Q3. Vision reranker fails silently to empty list

**Location:** `insightforge/stages/llm_processing.py:901-917`

**Problem:** When the vision reranker returns frame IDs that don't match the
`id_to_frame` mapping (e.g. due to ID format mismatch), `ranked_frames` ends up
empty. The code returns `[]` instead of falling back to heuristic ranking.

**Impact:** Entire sections lose all their frames with no warning in the output.
The user sees text-only sections even though relevant frames exist.

**Suggested fix:** If `ranked_frames` is empty after ID filtering, fall through to
the heuristic ranking path instead of returning early.

---

## Q4. JSON parsing regex too aggressive in LLM processing

**Location:** `insightforge/stages/llm_processing.py:1004-1023`

**Problem:** `_parse_json_response()` uses `r'\{[^{}]*"heading"[^{}]*\}'` to extract
JSON from LLM responses. This regex cannot match nested objects (e.g. a heading JSON
containing metadata sub-objects). It can also match partial objects if the LLM output
contains multiple brace pairs.

**Impact:** Malformed or incomplete section data is parsed, producing degraded notes
with missing fields or truncated content.

**Suggested fix:** Use the balanced-brace JSON finder (same approach as the
`_find_json_objects` fix applied to `ollama_provider.py`) or try `json.loads()` on
progressively larger substrings anchored at `{`.

---

## Q5. Topic boundary weights are hardcoded

**Location:** `insightforge/stages/llm_processing.py:778-784`

**Problem:** The boundary score that determines where topics split uses fixed weights:
- lexical_shift: 0.45
- transition_signal: 0.30
- gap_signal: 0.10
- visual_signal: 0.15

Different video types benefit from different weightings. Lectures have strong
transition signals ("next, let's talk about..."). Demos have strong visual signals.
Interviews have strong gap signals (pauses between questions).

**Impact:** Section boundaries may not match natural topic shifts for certain video
types, producing sections that split mid-thought or merge distinct topics.

**Suggested fix:** Move weights to `config/default.yaml` under `llm_processing.boundary_weights`
and provide presets (e.g. `config/presets/lecture.yaml`, `demo.yaml`).

---

## Q6. `_parse_score()` in importance.py has zero test coverage

**Location:** `insightforge/stages/importance.py:124-177`

**Problem:** This function handles 10+ edge cases for extracting importance scores
from LLM responses (bare floats, JSON objects, score patterns, 0-10 scale
normalization). None of these paths are tested.

**Impact:** If the LLM response format changes or a new model returns scores
differently, the parser may silently return 0.5 (the default), making all chunks
appear equally important. The user gets notes with no prioritization.

**Suggested fix:** Add unit tests for all branches: bare float, `{"score": 0.8}`,
`Score: 7/10`, `0-10` scale, malformed input, empty string.

---

## Q7. Formatter doesn't validate frame paths exist on disk

**Location:** `insightforge/stages/formatter.py:511-515`

**Problem:** `_frame_rel_path()` generates a relative path for Markdown image
references but never checks whether the frame file actually exists on disk.

**Impact:** Broken image links in the output Markdown. The user sees
`![frame](frames/frame_0003.jpg)` but the image is missing.

**Suggested fix:** Add an existence check and log a warning for missing frames,
or skip the frame reference entirely.

---

## Q8. Transcript block generation uses unstable sort

**Location:** `insightforge/stages/formatter.py:274-306`

**Problem:** Sections with identical `timestamp_start` and `timestamp_end` have no
tiebreaker in the sort. Python's `sorted()` is stable, but if two sections share
timestamps, their relative order depends on input order, which may vary between runs.

**Impact:** Non-deterministic output — running the same video twice could produce
transcript blocks in different orders.

**Suggested fix:** Add `section_id` as a tiebreaker:
```python
sorted(sections, key=lambda s: (s.timestamp_start, s.timestamp_end, s.section_id))
```

---

## Q9. Alignment stage doesn't validate segment ordering

**Location:** `insightforge/stages/alignment.py:77-103`

**Problem:** `_fill_gaps()` assumes segments are sorted by start time but never
validates this. If an upstream stage produces out-of-order segments, gap calculations
become incorrect (negative gaps, missing fills).

**Impact:** Transcript gaps may not be filled, producing choppy notes with missing
context between sections.

**Suggested fix:** Sort segments by `start` at the top of `_fill_gaps()` or assert
ordering and log a warning if violated.

---

## Q10. Unused `context_window` config field

**Location:** `config/default.yaml:7`

**Problem:** The Ollama config has `context_window: 8192` but no code reads this
value. Users may think they're configuring the context window, but changes have no
effect.

**Impact:** User confusion. Someone increasing `context_window` to handle longer
videos would see no change in behavior.

**Suggested fix:** Either wire `context_window` into the Ollama provider (to set
`num_ctx` in the API request) or remove the field from the config.

---

## Q11. HTML export may produce broken frame references

**Location:** `insightforge/storage/html_export.py:71-74`

**Problem:** Frame path resolution tries `output.frames_dir / frame.path.name`, but
if the frame was extracted to a work directory and not copied to the output, the
candidate path won't exist. The code falls back to the original `frame.path`, which
may point to a cleaned-up work directory.

**Impact:** HTML viewer shows broken images for frames.

**Suggested fix:** Validate that the resolved path exists before using it, and log
a warning listing which frames are missing.

---

## Q12. `--verbose` CLI flag may not enable debug logging

**Location:** `insightforge/cli.py:40-42`

**Problem:** The `--verbose` flag sets the root logger level to DEBUG, but the
InsightForge logger (from `utils/logging.py`) may use its own level configuration
that overrides the root.

**Impact:** Users passing `--verbose` see no additional debug output.

**Suggested fix:** Also set the `insightforge` logger level, or have `setup_logging`
respect a verbose flag.

---

## Priority

| Priority | Issues |
|----------|--------|
| High (affects note quality directly) | Q1, Q2, Q3, Q4, Q6 |
| Medium (affects robustness/correctness) | Q7, Q8, Q9, Q11 |
| Low (config/DX issues) | Q5, Q10, Q12 |
