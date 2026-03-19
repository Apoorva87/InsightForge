# InsightForge — Future Work: Home Dashboard

This document describes a planned local web dashboard for InsightForge.
This is a design document only — not yet implemented.

---

## Concept

A local web dashboard served at `localhost:8000` for:

- Browsing and searching YouTube
- Previewing videos before processing
- Submitting videos to a processing queue
- Tracking processing progress in real time
- Managing the library of processed videos

### Video Preview Strategy

YouTube iframe embeds now show ads. The better approach is to use iframes for
casual browsing and discovery, then switch to locally downloaded video for real
viewing. Alternatively, a yt-dlp streaming proxy could serve ad-free local
previews.

### Tech Stack

- **Backend**: FastAPI
- **Queue/Storage**: SQLite
- **Worker**: Background process calling existing `pipeline.run()`
- **Frontend**: Vanilla HTML/JS (consistent with the current viewer)
- **Progress**: Server-Sent Events (SSE) for real-time updates

---

## Architecture

```
Home Dashboard (localhost:8000)

+---------------------------+------------------------------------------+
|  Left Sidebar             |  Main Area                               |
|                           |                                          |
|  Processing Queue         |  YouTube search/browse with embed        |
|    - progress % per item  |  previews                                |
|                           |                                          |
|  Completed Library        |  Paste URL bar                           |
|    - delete buttons       |                                          |
|                           |  "Process" button                        |
|                           |                                          |
|  Click completed video    |                                          |
|  -> opens viewer/index    |                                          |
+---------------------------+------------------------------------------+
```

---

## Phases

### Phase 1 — Queue + Library Dashboard (MVP)

- Paste URL bar to submit a video to the processing queue
- Left sidebar shows:
  - **Queue**: items in progress with stage-based progress indicator
    (9 pipeline stages, each worth roughly 11%)
  - **Completed library**: finished videos
- Click a completed video to open the existing viewer
- Delete button on library items (removes the output folder + SQLite row,
  with a confirmation prompt)
- Implementation scope: single FastAPI process, SQLite database,
  approximately 400 lines Python + 300 lines HTML/JS

### Phase 2 — Search + Preview

- Search bar using `yt-dlp ytsearch` as a YouTube Data API alternative
  (no API key needed, roughly 3-5 seconds per search)
- Results displayed as cards with YouTube embed for preview
- "Process this" button on each search result card
- Channel browsing support

### Phase 3 — Nice-to-Haves

- **Batch processing**: select multiple search results and queue them all
- **Tags/folders**: organize processed videos into categories
- **Re-process**: run the pipeline again with different settings
  (e.g., educational mode vs. concise mode)
- **Disk usage indicator** + bulk cleanup of old outputs
- **yt-dlp streaming proxy** for ad-free local video preview

---

## Design Notes

- Do not try to replicate YouTube's recommendation algorithm. Focus on
  search and paste-URL as the primary workflows.
- YouTube Data API free tier allows 10,000 units/day (roughly 100
  searches/day). Using `yt-dlp ytsearch` is simpler and has no quota
  for a local tool.
- The `relatedToVideoId` parameter in the YouTube Data API was deprecated
  in 2023 and should not be relied upon.
- **Progress tracking**: the pipeline already logs stage completions.
  The dashboard only needs to emit SSE events at each stage transition.
