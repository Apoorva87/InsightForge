# Issues

## Review Notes

1. Hosted AI chat currently sends the full transcript with every question.
This is a context-limit and latency risk, especially for long videos and local models. It should move to transcript retrieval so only the most relevant spans are sent per question.

2. Final-answer-only cleanup in hosted chat is still fragile.
The current stripping removes `<think>...</think>` and a couple of simple prefixes, but it can still leak reasoning if a model formats it differently. This should be hardened if we keep model thinking enabled.

3. ~~Snapshot captions are improved but are not true summaries yet.~~
**FIXED** — `_frame_caption` now scores sentences by proximity to the frame timestamp (weighted word overlap × temporal closeness) and picks the best 1-2 sentences. Uses a regex sentence splitter that respects abbreviations/decimals instead of naive `.split(".")`.

4. ~~`run.sh` help text is stale relative to the current HTML viewer.~~
**FIXED** — Updated help text to say "inline frame snapshots" instead of "embedded images/clips".

5. ~~The HTML viewer no longer carries `FinalOutput.video_url`, so the "Open Original Video" button never opens the source.~~
**FIXED** — `formatter.run()` now passes `video_url` through to `FinalOutput(...)`.

6. ~~`insightforge/audio.py` drops sections whose headings stay at higher levels once any `###` sections appear, so post-run `audio-summary` output can silently omit entire branches from the spoken summary when nested subsections exist.~~
**FIXED** — `_leaf_audio_sections` now checks whether each section has an immediate child rather than filtering by max level, so standalone parent-level sections are preserved.

7. ~~The pipeline audio summary (`_build_audio_text` in `insightforge/pipeline.py`) walks top-level sections rather than leaf sections, so hierarchical runs describe only parents and never speak subsection summaries/key points.~~
**FIXED** — `_build_audio_text` now calls `_leaf_sections()` to recursively collect leaf `NoteSection` objects (including the `level <= 0.0` fallback path).

8. ~~Hosted viewer chat still hardcodes LMStudio in `_viewer_config`.~~
**FIXED** — `_viewer_config` now accepts the `LLMRouter`, probes each provider via `is_available()`, and picks the first reachable one — matching the router's actual fallback behavior.

## Open Issues

| # | Issue | Difficulty |
|---|-------|------------|
| 1 | Chat sends full transcript per question — needs retrieval | Hard |
| 2 | Think-tag stripping is fragile across model formats | Medium |

## Suggested Follow-Up

- Add transcript retrieval for hosted chat instead of sending the full transcript.
- Harden reasoning stripping / final-answer extraction for chat responses.
