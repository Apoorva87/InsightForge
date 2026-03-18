# HTML Viewer & Transcript Synchronization — Technical Reference

This document explains how the InsightForge HTML viewer works, with emphasis on
the video-transcript synchronization feature.

---

## High-Level Architecture

```
┌──────────────┐     ┌──────────────┐     ┌─────────────────────┐
│  cli.py      │────▶│  pipeline.py │────▶│  storage/writer.py  │
│  --html on   │     │  Stage 9     │     │  write_output()     │
└──────────────┘     └──────────────┘     └─────────┬───────────┘
                                                    │
                                          calls write_html_viewer()
                                                    │
                                          ┌─────────▼───────────┐
                                          │ storage/html_export  │
                                          │ .py                  │
                                          │                      │
                                          │ Generates:           │
                                          │  viewer/index.html   │
                                          │  viewer/notes.html   │
                                          └──────────────────────┘
```

### Entry Points

| Path | Role |
|------|------|
| `insightforge/cli.py:29` | `--html on\|off` CLI flag |
| `insightforge/pipeline.py` | Passes `html_enabled` through Stage 9 |
| `insightforge/storage/writer.py:149` | Calls `write_html_viewer()` |
| `insightforge/storage/html_export.py:15` | `write_html_viewer()` — main export function |
| `run.sh` | Shell wrapper, `--html on` flag |
| `view.sh` | Interactive viewer launcher (`--html`, `--host-html` modes) |

---

## Data Flow: From Pipeline to HTML

```
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ TranscriptResult │    │ FinalOutput      │    │ VideoMetadata    │
│ .segments[]      │    │ .sections[]      │    │ .title, .channel │
│  .start (float)  │    │  .timestamp_start│    │ .work_dir        │
│  .end   (float)  │    │  .timestamp_end  │    └──────────────────┘
│  .text  (str)    │    │  .heading        │
└────────┬─────────┘    │  .key_points     │
         │              │  .frames[]       │
         │              │  .subsections[]  │
         │              └────────┬─────────┘
         │                       │
         ▼                       ▼
  ┌──────────────────────────────────────┐
  │   write_html_viewer()               │
  │                                      │
  │   _serialize_section()  ←─── per section, filters transcript     │
  │     segments where seg.end > section.start                       │
  │     AND seg.start < section.end                                  │
  │                                      │
  │   _serialize_segment()  ←─── {start, end, timestamp, text}      │
  │                                      │
  │   Embeds DATA = { sections, transcript, title, ... }             │
  │   as JSON inside <script> tag                                    │
  └──────────────────────────────────────┘
```

### Key Serialization Functions

| Function | File:Line | Purpose |
|----------|-----------|---------|
| `write_html_viewer()` | `html_export.py:15` | Top-level; builds data dict, writes both HTML files |
| `_serialize_section()` | `html_export.py:48` | Converts `NoteSection` → dict with filtered transcript segments |
| `_serialize_segment()` | `html_export.py:105` | Converts `TranscriptSegment` → `{start, end, timestamp, text}` |
| `_build_html()` | `html_export.py` | Generates the full HTML string with embedded CSS + JS |
| `_build_notes_html()` | `html_export.py` | Generates the notes-only HTML page |

---

## HTML Viewer Layout

```
┌────────────────────────────────────────────────────────────┐
│                        Header Bar                          │
├──────────┬─────────────────────────────┬───────────────────┤
│          │                             │                   │
│  Section │     Main Content Area       │   Transcript      │
│  Nav     │                             │   Pane            │
│  (left)  │  ┌───────────────────────┐  │                   │
│          │  │   <video> element     │  │  [Section | Full] │
│  - Sec 1 │  │   (source-video)     │  │  tabs             │
│  - Sec 2 │  └───────────────────────┘  │                   │
│  - Sec 3 │                             │  ┌─────────────┐  │
│  - ...   │  Section heading            │  │ 00:00 text  │  │
│          │  Summary                    │  │ 00:05 text  │◀─┤── highlighted
│          │  Key points                 │  │ 00:10 text  │  │   active line
│          │  Frame gallery              │  │ ...         │  │
│          │                             │  └─────────────┘  │
├──────────┴─────────────────────────────┴───────────────────┤
│                    Chat Panel (optional)                    │
└────────────────────────────────────────────────────────────┘
```

---

## Transcript Synchronization — Detailed Flow

### State Variables (JavaScript)

```javascript
transcriptMode      // "section" (filtered) or "full" (all segments)
currentSection      // Currently displayed NoteSection object
lastHighlightedStamp // Prevents redundant scroll operations
transcriptTrackingHandle // requestAnimationFrame handle
```

### Synchronization Flow Diagram

```
Video playback starts
        │
        ▼
"play" event fires
        │
        ▼
startTranscriptTracking()          ◀── html_export.py:1070
        │
        ▼
requestAnimationFrame loop (tick)  ◀── ~60fps
        │
        ├──▶ syncTranscriptHighlight()    ◀── html_export.py:1015
        │         │
        │         ├── Get currentTime from video.currentTime
        │         │
        │         ├── [Section mode only] Check if time crossed
        │         │   a section boundary via findActiveSectionByTime()
        │         │         │
        │         │         ├── Same section → continue to highlighting
        │         │         │
        │         │         └── New section → selectSection()
        │         │                   │
        │         │                   ├── Update nav, heading, points, gallery
        │         │                   ├── renderTranscript()  ◀── re-renders lines
        │         │                   │        │
        │         │                   │        └── syncTranscriptHighlight()  (re-entrant)
        │         │                   │                  └── Now same section → highlights
        │         │                   └── return (original call exits early)
        │         │
        │         ├── Query all .transcript-line elements
        │         │
        │         ├── For each line: compare currentTime to
        │         │   line.dataset.start / line.dataset.end
        │         │   with ±0.12s tolerance
        │         │
        │         ├── Toggle .active CSS class on matching line
        │         │
        │         └── Smooth-scroll transcript pane to center
        │             the active line (if changed)
        │
        └── if video not paused/ended → schedule next frame

Also triggered by:
  "timeupdate"    → syncTranscriptHighlight()  (~4x/sec)
  "seeking"       → syncTranscriptHighlight()
  "seeked"        → syncTranscriptHighlight()
  "loadedmetadata"→ syncTranscriptHighlight()
  "pause"/"ended" → stopTranscriptTracking() (cancels RAF loop)
```

### Key Functions

| Function | Location (in embedded JS) | Purpose |
|----------|--------------------------|---------|
| `syncTranscriptHighlight(overrideTime)` | `html_export.py:1015` | Core sync: finds active line by time, toggles `.active`, scrolls |
| `startTranscriptTracking()` | `html_export.py:1070` | Starts RAF loop calling `syncTranscriptHighlight` at ~60fps |
| `stopTranscriptTracking()` | `html_export.py:1063` | Cancels the RAF loop |
| `renderTranscript()` | `html_export.py:974` | Clears and rebuilds transcript lines from data; calls sync at end |
| `selectSection(id, shouldSeek)` | `html_export.py:823` | Switches displayed section, re-renders transcript, optionally seeks |
| `findActiveSectionByTime(seconds)` | `html_export.py:909` | Finds deepest section whose time range contains `seconds` |

### Highlighting Mechanism

Each transcript line is a `<button>` with `data-start` and `data-end` attributes (float seconds).

```html
<button class="transcript-line" data-start="12.5" data-end="16.3">
  <span class="stamp">00:12</span>
  <span>The actual transcript text...</span>
</button>
```

The `.active` class applies a highlighted border and background gradient:

```css
.transcript-line.active {
  border-color: var(--accent);
  background: linear-gradient(180deg, rgba(12,108,102,0.14), rgba(12,108,102,0.05));
  box-shadow: inset 0 0 0 1px rgba(12,108,102,0.08);
}
```

Clicking a transcript line calls `seekTo(line.start)` to jump the video to that timestamp.

---

## Transcript Modes

| Mode | Data Source | Behavior |
|------|------------|----------|
| **Section** (default) | `currentSection.transcript` | Shows only segments within the selected section's time range. Auto-switches sections as video plays. |
| **Full** | `DATA.transcript` (all segments) | Shows entire transcript. No auto-section-switching. Highlights the current line. |

Toggled via the `[Selected Section | Full Transcript]` tab buttons above the transcript pane.

---

## Viewer Server (Optional Chat)

| File | Purpose |
|------|---------|
| `insightforge/viewer_server.py` | HTTP server on `localhost:8765` serving the HTML viewer |
| Endpoint: `/__insightforge/chat` | POST endpoint for transcript-aware LLM chat |

When launched via `view.sh --host-html`, the viewer server:
1. Serves the `viewer/` directory as static files
2. Loads `transcript.txt` as context for chat
3. Routes chat questions through the configured LLM (Ollama)
4. Strips thinking/reasoning blocks from responses

---

## Bug Fix Applied

### Problem: Event Object Passed as Time Override

**Location:** `html_export.py:1117-1120` (event listener registration)

When `syncTranscriptHighlight` was registered directly as an event handler:
```javascript
sourceVideo.addEventListener("timeupdate", syncTranscriptHighlight);
```

The browser passed the `Event` object as the first argument (`overrideTime`).
Since `Event ?? fallback` returns the Event (not null/undefined), `currentTime`
became the Event object. All numeric comparisons (`currentTime >= start`) evaluated
to `NaN`/`false`, so no transcript line was ever highlighted.

**Fix:** Wrap in arrow functions so `overrideTime` defaults to `null`:
```javascript
sourceVideo.addEventListener("timeupdate", () => syncTranscriptHighlight());
```

This ensures `currentTime` correctly falls back to `video.currentTime`.

---

## File Reference

```
insightforge/
├── cli.py                       ← --html on|off flag (line 29)
├── pipeline.py                  ← Passes html_enabled to writer
├── models/
│   ├── output.py                ← FinalOutput, NoteSection (timestamps, sections)
│   └── transcript.py            ← TranscriptResult, TranscriptSegment (start/end/text)
├── stages/
│   └── (stages 1-8 produce the data consumed by the viewer)
├── storage/
│   ├── writer.py                ← write_output() calls write_html_viewer() (line 149)
│   ├── html_export.py           ← HTML generation + embedded JS for sync (1500+ lines)
│   └── paths.py                 ← Output directory structure
├── viewer_server.py             ← Optional HTTP server + chat endpoint
└── utils/
    └── config.py                ← viewer config from default.yaml

run.sh                           ← --html on flag for processing
view.sh                          ← --html / --host-html for viewing
tests/unit/test_html_export.py   ← Unit tests for HTML generation
```
