"""Static HTML viewer export for InsightForge output."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from insightforge.models.output import FinalOutput, NoteSection
from insightforge.models.transcript import TranscriptResult, TranscriptSegment
from insightforge.models.video import VideoMetadata


def write_html_viewer(
    output: FinalOutput,
    metadata: VideoMetadata,
    transcript: Optional[TranscriptResult],
    output_dir: Path,
    viewer_config: Optional[dict] = None,
) -> tuple[Path, Path]:
    """Write a browsable HTML viewer for one processed video."""
    viewer_dir = output_dir / "viewer"
    viewer_dir.mkdir(parents=True, exist_ok=True)
    html_path = viewer_dir / "index.html"
    notes_path = viewer_dir / "notes.html"

    data = {
        "title": output.title,
        "channel": output.channel,
        "duration": _format_time(output.duration_seconds),
        "video_url": output.video_url,
        "executive_summary": output.executive_summary,
        "video_path": _rel(output.source_video_path, viewer_dir),
        "notes_html_path": "notes.html",
        "chat": (viewer_config or {}).get("chat", {"enabled": False}),
        "sections": [_serialize_section(section, transcript, output, viewer_dir) for section in output.sections],
        "transcript": [_serialize_segment(segment) for segment in (transcript.segments if transcript else [])],
    }

    html = _build_html(data)
    html_path.write_text(html, encoding="utf-8")
    notes_html = _build_notes_html(data)
    notes_path.write_text(notes_html, encoding="utf-8")
    return html_path, notes_path


def _serialize_section(
    section: NoteSection,
    transcript: Optional[TranscriptResult],
    output: FinalOutput,
    viewer_dir: Path,
) -> dict:
    clip_path = None
    if output.clips_dir:
        candidate = output.clips_dir / f"{section.section_id}.mp4"
        if candidate.exists():
            clip_path = _rel(candidate, viewer_dir)

    transcript_segments = []
    if transcript:
        transcript_segments = [
            _serialize_segment(seg)
            for seg in transcript.segments
            if seg.end > section.timestamp_start and seg.start < section.timestamp_end
        ]

    serialized_frames = []
    for frame in sorted(section.frames, key=lambda frame: frame.timestamp):
        frame_path = frame.path
        if output.frames_dir is not None:
            candidate = output.frames_dir / frame.path.name
            if candidate.exists():
                frame_path = candidate
        if frame_path.exists():
            # Use VLM description if available, fall back to transcript caption
            caption = frame.description if frame.description else _frame_caption(frame.timestamp, transcript)
            serialized_frames.append(
                {
                    "path": _rel(frame_path, viewer_dir),
                    "timestamp": frame.timestamp,
                    "timestamp_str": _format_time(frame.timestamp),
                    "caption": caption,
                    "content_score": frame.content_score or 0.0,
                    "frame_type": frame.frame_type or "other",
                    "description": frame.description or "",
                    "ocr_text": frame.ocr_text or "",
                }
            )

    return {
        "id": section.section_id,
        "heading": section.heading,
        "summary": section.summary,
        "key_points": section.key_points,
        "formulas": section.formulas,
        "code_snippets": section.code_snippets,
        "examples": section.examples,
        "start": section.timestamp_start,
        "end": section.timestamp_end,
        "timestamp": section.timestamp_str,
        "timestamp_end": section.timestamp_end_str,
        "is_leaf": section.is_leaf,
        "frames": serialized_frames,
        "clip_path": clip_path,
        "transcript": transcript_segments,
        "subsections": [
            _serialize_section(subsection, transcript, output, viewer_dir)
            for subsection in section.subsections
        ],
    }


def _serialize_segment(segment: TranscriptSegment) -> dict:
    return {
        "start": segment.start,
        "end": segment.end,
        "timestamp": segment.timestamp_str,
        "text": segment.text,
    }


def _build_html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_escape_html(data["title"])} - InsightForge Viewer</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css" crossorigin="anonymous">
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js" crossorigin="anonymous"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js" crossorigin="anonymous"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/marked@12.0.0/marked.min.js"></script>
  <style>
    :root {{
      --bg: #f5f1e8;
      --panel: #fffdf8;
      --panel-2: #f0e8d7;
      --ink: #192126;
      --muted: #5f665f;
      --accent: #0c6c66;
      --accent-2: #d97b29;
      --border: #d7c7af;
      --shadow: 0 14px 40px rgba(25, 33, 38, 0.08);
      --radius: 18px;
      --mono: "IBM Plex Mono", "SFMono-Regular", ui-monospace, monospace;
      --sans: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: var(--sans);
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(217, 123, 41, 0.12), transparent 24rem),
        radial-gradient(circle at top right, rgba(12, 108, 102, 0.12), transparent 26rem),
        linear-gradient(180deg, #faf7f0 0%, var(--bg) 100%);
    }}
    .app {{
      display: grid;
      grid-template-columns: 300px minmax(0, 1fr) 360px;
      height: 100vh;
      gap: 18px;
      padding: 18px;
    }}
    .panel {{
      background: rgba(255, 253, 248, 0.92);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
      backdrop-filter: blur(12px);
      min-height: 0;
    }}
    .sidebar, .rightpane {{
      display: flex;
      flex-direction: column;
      min-height: 0;
    }}
    .sidebar header, .main header, .rightpane header {{
      padding: 10px 16px;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(180deg, rgba(255,255,255,0.65), rgba(240,232,215,0.75));
    }}
    h1, h2, h3, h4, p {{ margin: 0; }}
    .eyebrow {{
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.68rem;
      margin-bottom: 0.2rem;
    }}
    .title {{
      font-size: 1.15rem;
      line-height: 1.2;
      margin-bottom: 0.25rem;
    }}
    .meta {{
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .summary-box {{
      margin-top: 0.9rem;
      padding: 0.95rem 1rem;
      border-radius: 14px;
      background: var(--panel-2);
      color: var(--ink);
      line-height: 1.5;
      max-height: 30vh;
      overflow: auto;
    }}
    .sidebar-body {{
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      min-height: 0;
      overflow: hidden;
    }}
    .nav-list {{
      padding: 12px;
      overflow: auto;
      flex: 1 1 auto;
      min-height: 0;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .nav-item {{
      border: 1px solid var(--border);
      background: #fff;
      border-radius: 14px;
      padding: 10px 12px;
      cursor: pointer;
      text-align: left;
      transition: transform 120ms ease, border-color 120ms ease, background 120ms ease;
    }}
    .nav-item:hover, .nav-item.active {{
      transform: translateY(-1px);
      border-color: var(--accent);
      background: #f7fbfb;
    }}
    .nav-item .time {{
      font-family: var(--mono);
      color: var(--accent);
      font-size: 0.8rem;
      margin-bottom: 0.35rem;
    }}
    .nav-item .heading {{
      font-weight: 600;
      line-height: 1.3;
    }}
    .nav-children {{
      margin-left: 14px;
      padding-left: 10px;
      border-left: 1px dashed var(--border);
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .main {{
      display: flex;
      flex-direction: column;
      min-height: 0;
    }}
    .main-body {{
      padding: 18px 20px 24px;
      overflow: auto;
      display: grid;
      gap: 18px;
      align-content: start;
    }}
    .video-shell {{
      position: sticky;
      top: 0;
      z-index: 2;
      display: grid;
      gap: 12px;
      padding: 12px;
      border-radius: 18px;
      background: rgba(255,253,248,0.96);
      border: 1px solid var(--border);
      resize: vertical;
      overflow: auto;
      min-height: 320px;
      max-height: 72vh;
    }}
    video {{
      width: 100%;
      height: 100%;
      min-height: 280px;
      max-height: 65vh;
      border-radius: 16px;
      background: #111;
      border: 1px solid rgba(0,0,0,0.08);
    }}
    .action-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }}
    button, .chip {{
      appearance: none;
      border: 1px solid var(--border);
      background: #fff;
      border-radius: 999px;
      padding: 0.6rem 0.9rem;
      font: inherit;
      cursor: pointer;
      color: var(--ink);
    }}
    button:hover {{
      border-color: var(--accent);
      color: var(--accent);
    }}
    button.active-toggle {{
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }}
    .icon-button {{
      width: 2.35rem;
      height: 2.35rem;
      padding: 0;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 1rem;
      font-weight: 700;
      line-height: 1;
      position: relative;
    }}
    .icon-button[data-tooltip]:hover::after,
    .icon-button[data-tooltip]:focus-visible::after {{
      content: attr(data-tooltip);
      position: absolute;
      bottom: calc(100% + 8px);
      left: 50%;
      transform: translateX(-50%);
      white-space: nowrap;
      background: rgba(25, 33, 38, 0.96);
      color: #fffdf8;
      padding: 6px 8px;
      border-radius: 8px;
      font-size: 0.76rem;
      font-weight: 500;
      line-height: 1.2;
      box-shadow: 0 10px 24px rgba(25, 33, 38, 0.18);
      z-index: 10;
      pointer-events: none;
    }}
    .section-card {{
      display: grid;
      gap: 14px;
      padding: 20px;
      border-radius: 18px;
      background: rgba(255,255,255,0.82);
      border: 1px solid var(--border);
    }}
    .section-head {{
      display: flex;
      gap: 8px;
      align-items: baseline;
      flex-wrap: wrap;
    }}
    .section-meta-text {{
      font-family: var(--mono);
      font-size: 0.78rem;
      color: var(--muted);
    }}
    .section-meta-text .accent {{
      color: var(--accent);
    }}
    .section-title {{
      font-size: 1.35rem;
      line-height: 1.2;
    }}
    .section-summary {{
      font-size: 1.02rem;
      line-height: 1.65;
      color: #253038;
    }}
    ul.points {{
      margin: 0;
      padding-left: 1.25rem;
      display: grid;
      gap: 0.65rem;
      line-height: 1.55;
    }}
    .annotated-points {{
      display: grid;
      gap: 14px;
    }}
    .annotated-point {{
      display: grid;
      gap: 10px;
      padding: 12px 14px;
      border: 1px solid var(--border);
      border-radius: 14px;
      background: #fff;
    }}
    .annotated-point p {{
      margin: 0;
      line-height: 1.6;
      color: #223039;
    }}
    .annotated-point figure {{
      margin: 0;
      display: grid;
      gap: 6px;
    }}
    .annotated-point img {{
      width: 100%;
      max-width: 420px;
      aspect-ratio: 16 / 9;
      object-fit: cover;
      border-radius: 12px;
      border: 1px solid rgba(0,0,0,0.06);
      cursor: pointer;
    }}
    .annotated-point figcaption {{
      font-family: var(--mono);
      color: var(--muted);
      font-size: 0.8rem;
    }}
    .gallery {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }}
    .thumb {{
      display: grid;
      gap: 8px;
      padding: 10px;
      border-radius: 14px;
      background: #fff;
      border: 1px solid var(--border);
    }}
    .thumb img {{
      width: 100%;
      aspect-ratio: 16 / 9;
      object-fit: cover;
      border-radius: 10px;
      border: 1px solid rgba(0,0,0,0.06);
      cursor: pointer;
    }}
    .thumb time {{
      font-family: var(--mono);
      color: var(--muted);
      font-size: 0.82rem;
    }}
    .rightpane-body {{
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      min-height: 0;
      overflow: hidden;
    }}
    .transcript-tabs {{
      display: flex;
      gap: 8px;
      padding: 14px 16px 0;
    }}
    .transcript-tabs button.active {{
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }}
    .transcript-list {{
      padding: 14px 16px 18px;
      overflow-y: auto;
      overflow-x: hidden;
      flex: 1 1 auto;
      min-height: 0;
      height: 100%;
      scroll-behavior: smooth;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .transcript-line {{
      display: grid;
      gap: 6px;
      width: 100%;
      text-align: left;
      border: 1px solid var(--border);
      background: #fff;
      border-radius: 14px;
      padding: 10px 12px;
      cursor: pointer;
    }}
    .transcript-line:hover {{
      border-color: var(--accent);
      background: #f7fbfb;
    }}
    .transcript-line.active {{
      border-color: var(--accent);
      background: linear-gradient(180deg, rgba(12,108,102,0.14), rgba(12,108,102,0.05));
      box-shadow: inset 0 0 0 1px rgba(12,108,102,0.08);
    }}
    .transcript-line .stamp {{
      font-family: var(--mono);
      color: var(--accent);
      font-size: 0.82rem;
    }}
    .subsections {{
      display: grid;
      gap: 12px;
    }}
    .subsection-card {{
      border: 1px solid var(--border);
      background: #fff;
      border-radius: 14px;
      padding: 14px 16px;
      display: grid;
      gap: 8px;
    }}
    .subsection-card .sub-time {{
      font-family: var(--mono);
      color: var(--accent);
      font-size: 0.8rem;
    }}
    .subsection-card h4 {{
      font-size: 1rem;
      line-height: 1.3;
    }}
    .subsection-card p {{
      line-height: 1.55;
      color: #314047;
    }}
    .chat-panel {{
      display: flex;
      flex-direction: column;
      gap: 12px;
      padding: 16px 16px 14px;
      border-top: 1px solid var(--border);
      background: rgba(255,255,255,0.84);
      min-height: 220px;
      height: 32vh;
      max-height: 58vh;
      resize: vertical;
      overflow: hidden;
    }}
    .chat-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .chat-head-actions {{
      display: inline-flex;
      gap: 8px;
      align-items: center;
    }}
    .chat-panel .icon-button {{
      width: 2rem;
      height: 2rem;
      font-size: 0.92rem;
    }}
    .chat-log {{
      overflow: auto;
      display: grid;
      gap: 10px;
      padding-right: 4px;
      flex: 1 1 auto;
      min-height: 0;
    }}
    .chat-msg {{
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: #fff;
      line-height: 1.55;
      white-space: pre-wrap;
    }}
    .chat-msg.user {{
      border-color: rgba(12,108,102,0.28);
      background: rgba(12,108,102,0.08);
    }}
    .chat-form {{
      display: grid;
      gap: 10px;
    }}
    .chat-form textarea {{
      width: 100%;
      min-height: 96px;
      resize: vertical;
      border-radius: 14px;
      border: 1px solid var(--border);
      padding: 12px 14px;
      font: inherit;
      background: #fff;
    }}
    .chat-actions {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .chat-meta {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .chat-options {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .chat-context {{
      color: var(--muted);
      font-size: 0.84rem;
      font-family: var(--mono);
    }}
    .chat-reset {{
      padding: 0.45rem 0.7rem;
      font-size: 0.88rem;
    }}
    .chat-status {{
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .edu-artifacts {{
      display: grid;
      gap: 12px;
      margin-top: 8px;
    }}
    .edu-block {{
      padding: 14px 16px;
      border-radius: 14px;
      border: 1px solid var(--border);
    }}
    .edu-block.formulas {{
      background: rgba(12,108,102,0.06);
      border-color: rgba(12,108,102,0.2);
    }}
    .edu-block.code {{
      background: #1e1e2e;
      color: #cdd6f4;
      font-family: var(--mono);
      font-size: 0.88rem;
      overflow-x: auto;
      white-space: pre-wrap;
    }}
    .edu-block.examples {{
      background: rgba(217,123,41,0.06);
      border-color: rgba(217,123,41,0.2);
    }}
    .edu-label {{
      font-size: 0.78rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 8px;
      color: var(--muted);
    }}
    .edu-block pre {{
      margin: 0;
      white-space: pre-wrap;
      font-family: var(--mono);
      font-size: 0.88rem;
    }}
    .edu-block .formula-item {{
      margin: 6px 0;
      font-size: 1.05rem;
    }}
    .edu-block .example-item {{
      padding: 8px 12px;
      border-left: 3px solid rgba(217,123,41,0.4);
      margin: 6px 0;
      line-height: 1.55;
    }}
    .rendered-md p {{ margin: 0 0 0.5em; line-height: 1.6; }}
    .rendered-md p:last-child {{ margin-bottom: 0; }}
    .empty {{
      color: var(--muted);
      line-height: 1.5;
      padding: 18px;
    }}
    /* Lightbox overlay */
    .lightbox-overlay {{
      display: none;
      position: fixed;
      inset: 0;
      z-index: 1000;
      background: rgba(0, 0, 0, 0.88);
      backdrop-filter: blur(8px);
      align-items: center;
      justify-content: center;
      flex-direction: column;
      gap: 12px;
      cursor: pointer;
    }}
    .lightbox-overlay.open {{
      display: flex;
    }}
    .lightbox-overlay img {{
      max-width: 92vw;
      max-height: 82vh;
      object-fit: contain;
      border-radius: 12px;
      cursor: default;
      box-shadow: 0 20px 60px rgba(0,0,0,0.5);
    }}
    .lightbox-caption {{
      color: #e0dcd4;
      font-size: 0.92rem;
      text-align: center;
      max-width: 80vw;
      line-height: 1.5;
    }}
    .lightbox-ocr {{
      color: #c8c4bc;
      font-size: 0.82rem;
      text-align: left;
      max-width: 70vw;
      max-height: 18vh;
      overflow: auto;
      padding: 10px 14px;
      background: rgba(255,255,255,0.08);
      border-radius: 10px;
      font-family: var(--mono);
      white-space: pre-wrap;
    }}
    .lightbox-nav {{
      position: fixed;
      top: 50%;
      transform: translateY(-50%);
      z-index: 1001;
      background: rgba(255,255,255,0.15);
      border: none;
      color: #fff;
      font-size: 2rem;
      width: 48px;
      height: 48px;
      border-radius: 50%;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 120ms ease;
      padding: 0;
    }}
    .lightbox-nav:hover {{
      background: rgba(255,255,255,0.3);
    }}
    .lightbox-prev {{ left: 16px; }}
    .lightbox-next {{ right: 16px; }}
    .lightbox-close {{
      position: fixed;
      top: 16px;
      right: 16px;
      z-index: 1001;
      background: rgba(255,255,255,0.15);
      border: none;
      color: #fff;
      font-size: 1.5rem;
      width: 40px;
      height: 40px;
      border-radius: 50%;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0;
    }}
    .lightbox-close:hover {{
      background: rgba(255,255,255,0.3);
    }}
    .lightbox-counter {{
      position: fixed;
      bottom: 16px;
      left: 50%;
      transform: translateX(-50%);
      color: rgba(255,255,255,0.6);
      font-size: 0.82rem;
      font-family: var(--mono);
    }}
    /* Frame type badges */
    .frame-badge {{
      display: inline-block;
      font-size: 0.68rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      padding: 2px 7px;
      border-radius: 6px;
      background: rgba(12,108,102,0.12);
      color: var(--accent);
      margin-left: 6px;
      vertical-align: middle;
    }}
    /* Larger inline thumbnails */
    .annotated-point img {{
      max-width: 500px;
    }}
    .thumb img {{
      min-height: 160px;
    }}
    /* OCR text below frames */
    .frame-ocr {{
      font-family: var(--mono);
      font-size: 0.8rem;
      color: var(--muted);
      background: rgba(0,0,0,0.03);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 10px;
      margin-top: 4px;
      white-space: pre-wrap;
      max-height: 120px;
      overflow: auto;
    }}
    .frame-ocr.code-ocr {{
      background: #1e1e2e;
      color: #cdd6f4;
      border-color: rgba(0,0,0,0.2);
    }}
    @media (max-width: 1180px) {{
      .app {{ grid-template-columns: 260px minmax(0, 1fr); }}
      .rightpane {{ grid-column: 1 / -1; min-height: 28vh; }}
    }}
    @media (max-width: 840px) {{
      .app {{ grid-template-columns: 1fr; height: auto; min-height: 100vh; padding: 12px; }}
      .sidebar {{ order: 2; }}
      .rightpane {{ order: 3; }}
      .main {{ order: 1; }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <aside class="panel sidebar">
      <header>
        <div class="eyebrow">InsightForge Viewer</div>
        <h1 class="title">{_escape_html(data["title"])}</h1>
        <div class="meta">{_escape_html(data["channel"])} · {_escape_html(data["duration"])}</div>
        {"<div class='summary-box' id='summary-box'></div>" if data.get("executive_summary") else ""}
      </header>
      <div class="sidebar-body">
        <div class="nav-list" id="nav-list"></div>
        <section class="chat-panel">
          <div class="chat-head">
            <div class="section-head">
              <span class="chip">AI Chat</span>
              <span class="meta" id="chat-mode"></span>
            </div>
            <div class="chat-head-actions">
              <button id="chat-popout" type="button" title="Pop out AI chat" aria-label="Pop out AI chat">⤢</button>
            </div>
          </div>
          <div class="chat-log" id="chat-log">
            <div class="chat-msg">Ask questions about the video. In hosted mode, the chat uses the local model plus the full transcript context.</div>
          </div>
          <form class="chat-form" id="chat-form">
            <textarea id="chat-input" placeholder="Ask a question about this video..."></textarea>
            <div class="chat-actions">
              <div class="chat-meta">
                <label class="chat-options"><input id="chat-web-search" type="checkbox" /> Enable web search</label>
                <span class="chat-context" id="chat-context-length">Context: 0 chars</span>
                <button class="chat-reset" id="chat-reset" type="button">Reset</button>
              </div>
              <span class="chat-status" id="chat-status">Hosted mode enables transcript-aware local chat.</span>
              <button id="chat-send" type="submit">Ask</button>
            </div>
          </form>
        </section>
      </div>
    </aside>
    <main class="panel main">
      <header>
        <div class="eyebrow">Browsable Notes</div>
        <h2 class="title" id="current-heading">Section</h2>
        <div class="meta" id="current-meta"></div>
      </header>
      <div class="main-body">
        <section class="video-shell">
          <video id="source-video" controls preload="metadata"></video>
          <div class="action-row">
            <button id="jump-start" type="button">Jump To Section Start</button>
            <button id="jump-end" type="button">Jump To Section End</button>
            <button id="toggle-frames" type="button">Show Explanatory Snapshots</button>
            <button id="open-notes-html" type="button">Open Notes HTML</button>
            <button id="open-source" type="button">Open Original Video</button>
          </div>
        </section>
        <section class="section-card">
          <div class="section-head">
            <span class="section-meta-text" id="current-time-chip"></span>
          </div>
          <p class="section-summary" id="current-summary"></p>
          <ul class="points" id="current-points"></ul>
          <div class="annotated-points" id="current-annotated" hidden></div>
          <div class="subsections" id="current-subsections"></div>
          <div class="gallery" id="current-gallery"></div>
        </section>
      </div>
    </main>
    <aside class="panel rightpane">
      <header>
        <div class="eyebrow">Transcript</div>
        <h3 class="title">Transcript Pane</h3>
        <div class="meta">Click any line to seek the local video.</div>
      </header>
      <div class="rightpane-body">
        <div class="transcript-tabs">
          <button id="tab-section" class="active" type="button">Selected Section</button>
          <button id="tab-full" type="button">Full Transcript</button>
        </div>
        <div class="transcript-list" id="transcript-list"></div>
      </div>
    </aside>
  </div>
  <!-- Lightbox overlay -->
  <div class="lightbox-overlay" id="lightbox">
    <button class="lightbox-close" id="lightbox-close" aria-label="Close">&times;</button>
    <button class="lightbox-nav lightbox-prev" id="lightbox-prev" aria-label="Previous">&lsaquo;</button>
    <button class="lightbox-nav lightbox-next" id="lightbox-next" aria-label="Next">&rsaquo;</button>
    <img id="lightbox-img" src="" alt="" />
    <div class="lightbox-caption" id="lightbox-caption"></div>
    <div class="lightbox-ocr" id="lightbox-ocr" hidden></div>
    <div class="lightbox-counter" id="lightbox-counter"></div>
  </div>
  <script>
    const DATA = {payload};
    const flatSections = [];
    const navList = document.getElementById("nav-list");
    const sourceVideo = document.getElementById("source-video");
    const summaryBox = document.getElementById("summary-box");
    const transcriptList = document.getElementById("transcript-list");
    const jumpStart = document.getElementById("jump-start");
    const jumpEnd = document.getElementById("jump-end");
    const toggleFrames = document.getElementById("toggle-frames");
    const openNotesHtml = document.getElementById("open-notes-html");
    const openSource = document.getElementById("open-source");
    const tabSection = document.getElementById("tab-section");
    const tabFull = document.getElementById("tab-full");
    const subsectionContainer = document.getElementById("current-subsections");
    const annotatedContainer = document.getElementById("current-annotated");
    const chatMode = document.getElementById("chat-mode");
    const chatLog = document.getElementById("chat-log");
    const chatForm = document.getElementById("chat-form");
    const chatInput = document.getElementById("chat-input");
    const chatWebSearch = document.getElementById("chat-web-search");
    const chatPopout = document.getElementById("chat-popout");
    const chatReset = document.getElementById("chat-reset");
    const chatSend = document.getElementById("chat-send");
    const chatStatus = document.getElementById("chat-status");
    const chatContextLength = document.getElementById("chat-context-length");
    let transcriptMode = "section";
    let currentSection = null;
    let lastHighlightedStamp = null;
    let showAnnotatedFrames = false;
    let chatPopupWindow = null;
    let chatHistory = [];
    let transcriptTrackingHandle = null;
    let userSelectedSectionUntil = 0;

    // Lightbox state
    const lightboxOverlay = document.getElementById("lightbox");
    const lightboxImg = document.getElementById("lightbox-img");
    const lightboxCaption = document.getElementById("lightbox-caption");
    const lightboxOcr = document.getElementById("lightbox-ocr");
    const lightboxCounter = document.getElementById("lightbox-counter");
    const lightboxClose = document.getElementById("lightbox-close");
    const lightboxPrev = document.getElementById("lightbox-prev");
    const lightboxNext = document.getElementById("lightbox-next");
    let lightboxFrames = [];
    let lightboxIndex = 0;

    function openLightbox(frames, index) {{
      lightboxFrames = frames;
      lightboxIndex = Math.max(0, Math.min(index, frames.length - 1));
      showLightboxFrame();
      lightboxOverlay.classList.add("open");
      document.body.style.overflow = "hidden";
    }}

    function closeLightbox() {{
      lightboxOverlay.classList.remove("open");
      document.body.style.overflow = "";
      lightboxFrames = [];
    }}

    function showLightboxFrame() {{
      if (!lightboxFrames.length) return;
      const frame = lightboxFrames[lightboxIndex];
      lightboxImg.src = frame.path;
      lightboxImg.alt = frame.caption || "";
      lightboxCaption.textContent = frame.caption
        ? `${{frame.timestamp_str}} · ${{frame.caption}}`
        : frame.timestamp_str;
      if (frame.ocr_text) {{
        lightboxOcr.textContent = frame.ocr_text;
        lightboxOcr.hidden = false;
        lightboxOcr.className = isCodeLike(frame.ocr_text) ? "lightbox-ocr code-ocr" : "lightbox-ocr";
      }} else {{
        lightboxOcr.hidden = true;
      }}
      lightboxCounter.textContent = `${{lightboxIndex + 1}} / ${{lightboxFrames.length}}`;
      lightboxPrev.style.display = lightboxFrames.length > 1 ? "" : "none";
      lightboxNext.style.display = lightboxFrames.length > 1 ? "" : "none";
    }}

    function lightboxStep(delta) {{
      if (!lightboxFrames.length) return;
      lightboxIndex = (lightboxIndex + delta + lightboxFrames.length) % lightboxFrames.length;
      showLightboxFrame();
    }}

    function isCodeLike(text) {{
      if (!text) return false;
      const codeIndicators = ["{{", "}}", "=>", "->", "def ", "class ", "function ", "import ", "return ", "const ", "let ", "var "];
      return codeIndicators.some(indicator => text.includes(indicator));
    }}

    lightboxClose.addEventListener("click", (e) => {{ e.stopPropagation(); closeLightbox(); }});
    lightboxPrev.addEventListener("click", (e) => {{ e.stopPropagation(); lightboxStep(-1); }});
    lightboxNext.addEventListener("click", (e) => {{ e.stopPropagation(); lightboxStep(1); }});
    lightboxImg.addEventListener("click", (e) => e.stopPropagation());
    lightboxOcr.addEventListener("click", (e) => e.stopPropagation());
    lightboxOverlay.addEventListener("click", closeLightbox);
    document.addEventListener("keydown", (e) => {{
      if (!lightboxOverlay.classList.contains("open")) return;
      if (e.key === "Escape") closeLightbox();
      else if (e.key === "ArrowLeft") lightboxStep(-1);
      else if (e.key === "ArrowRight") lightboxStep(1);
    }});

    const buttonConfigs = [
      {{ element: jumpStart, icon: "↦", title: "Jump to section start" }},
      {{ element: jumpEnd, icon: "↣", title: "Jump to section end" }},
      {{ element: toggleFrames, icon: "▤", title: "Show explanatory snapshots", activeTitle: "Hide explanatory snapshots" }},
      {{ element: openNotesHtml, icon: "☰", title: "Open notes-only HTML" }},
      {{ element: openSource, icon: "↗", title: "Open original video" }},
    ];

    if (summaryBox && DATA.executive_summary) {{
      summaryBox.textContent = DATA.executive_summary.replace(/\\*\\*/g, "");
    }}

    buttonConfigs.forEach(({{ element, icon, title }}) => {{
      if (!element) return;
      element.classList.add("icon-button");
      element.textContent = icon;
      element.title = title;
      element.dataset.tooltip = title;
      element.setAttribute("aria-label", title);
    }});
    if (chatPopout) {{
      chatPopout.classList.add("icon-button");
      chatPopout.dataset.tooltip = "Pop out AI chat";
    }}

    chatMode.textContent = DATA.chat?.enabled
      ? `Hosted local chat via ${{DATA.chat.provider}} · ${{DATA.chat.model}}`
      : "Hosted mode required for chat";

    if (DATA.video_path) {{
      sourceVideo.src = DATA.video_path;
    }} else {{
      sourceVideo.replaceWith(Object.assign(document.createElement("div"), {{
        className: "empty",
        textContent: "Local source video was not copied for this run, so seek controls are limited."
      }}));
      jumpStart.disabled = true;
      jumpEnd.disabled = true;
    }}

    function seekTo(seconds, autoplay = false) {{
      const video = document.getElementById("source-video");
      if (!video || !Number.isFinite(seconds)) return;
      video.currentTime = Math.max(0, seconds);
      if (autoplay && video.paused) {{
        video.play().catch(() => null);
      }}
      if (!autoplay) {{
        video.pause();
      }}
    }}

    function renderNav() {{
      navList.innerHTML = "";
      DATA.sections.forEach(section => navList.appendChild(renderNavItem(section, 0)));
    }}

    function renderNavItem(section, depth) {{
      flatSections.push(section);
      const wrapper = document.createElement("div");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "nav-item";
      button.dataset.sectionId = section.id;
      button.innerHTML = `
        <div class="time">${{section.timestamp}} - ${{section.timestamp_end}}</div>
        <div class="heading">${{escapeHtml(section.heading)}}</div>
      `;
      button.addEventListener("click", () => selectSection(section.id, true));
      wrapper.appendChild(button);

      if (section.subsections && section.subsections.length) {{
        const children = document.createElement("div");
        children.className = "nav-children";
        section.subsections.forEach(child => children.appendChild(renderNavItem(child, depth + 1)));
        wrapper.appendChild(children);
      }}
      return wrapper;
    }}

    function selectSection(sectionId, shouldSeek) {{
      currentSection = findSection(sectionId, DATA.sections);
      if (!currentSection) return;
      if (shouldSeek) userSelectedSectionUntil = Date.now() + 1500;
      document.querySelectorAll(".nav-item").forEach(item => {{
        item.classList.toggle("active", item.dataset.sectionId === sectionId);
      }});
      document.getElementById("current-heading").textContent = currentSection.heading;
      document.getElementById("current-meta").textContent = `${{currentSection.timestamp}} - ${{currentSection.timestamp_end}}`;
      document.getElementById("current-time-chip").innerHTML = `<span class="accent">${{currentSection.timestamp}} - ${{currentSection.timestamp_end}}</span>`;
      const summaryEl = document.getElementById("current-summary");
      summaryEl.innerHTML = renderMarkdown(currentSection.summary || "No summary available.");

      const points = document.getElementById("current-points");
      points.innerHTML = "";
      (currentSection.key_points || []).forEach(point => {{
        const li = document.createElement("li");
        li.textContent = point;
        points.appendChild(li);
      }});
      points.hidden = showAnnotatedFrames;

      annotatedContainer.hidden = !showAnnotatedFrames;
      annotatedContainer.innerHTML = "";
      if (showAnnotatedFrames) {{
        const annotatedData = buildAnnotatedPoints(currentSection);
        const annotatedFrameList = annotatedData.filter(item => item.frame).map(item => item.frame);
        annotatedData.forEach(item => {{
          const block = document.createElement("div");
          block.className = "annotated-point";
          const para = document.createElement("p");
          para.textContent = item.point;
          block.appendChild(para);
          if (item.frame) {{
            const figure = document.createElement("figure");
            const img = document.createElement("img");
            img.src = item.frame.path;
            img.alt = `${{currentSection.heading}} at ${{item.frame.timestamp_str}}`;
            const frameIdx = annotatedFrameList.indexOf(item.frame);
            img.addEventListener("click", () => openLightbox(annotatedFrameList, frameIdx));
            const caption = document.createElement("figcaption");
            const badge = item.frame.frame_type && item.frame.frame_type !== "other"
              ? ` <span class="frame-badge">${{escapeHtml(item.frame.frame_type)}}</span>` : "";
            caption.innerHTML = item.frame.caption
              ? `${{escapeHtml(item.frame.timestamp_str)}} · ${{escapeHtml(item.frame.caption)}}${{badge}}`
              : `Snapshot ${{escapeHtml(item.frame.timestamp_str)}}${{badge}}`;
            figure.appendChild(img);
            figure.appendChild(caption);
            if (item.frame.ocr_text) {{
              const ocr = document.createElement("div");
              ocr.className = isCodeLike(item.frame.ocr_text) ? "frame-ocr code-ocr" : "frame-ocr";
              ocr.textContent = item.frame.ocr_text;
              figure.appendChild(ocr);
            }}
            block.appendChild(figure);
          }}
          annotatedContainer.appendChild(block);
        }});
      }}

      subsectionContainer.innerHTML = "";
      if (currentSection.subsections && currentSection.subsections.length) {{
        currentSection.subsections.forEach(subsection => {{
          const card = document.createElement("div");
          card.className = "subsection-card";
          card.innerHTML = `
            <div class="sub-time">${{subsection.timestamp}} - ${{subsection.timestamp_end}}</div>
            <h4>${{escapeHtml(subsection.heading)}}</h4>
            <p>${{escapeHtml(subsection.summary || "No summary available.")}}</p>
          `;
          card.addEventListener("click", () => selectSection(subsection.id, true));
          subsectionContainer.appendChild(card);
        }});
      }}

      const gallery = document.getElementById("current-gallery");
      gallery.innerHTML = "";
      gallery.hidden = showAnnotatedFrames;
      const effectiveFrames = getEffectiveFrames(currentSection);
      effectiveFrames.forEach((frame, idx) => {{
        const card = document.createElement("div");
        card.className = "thumb";
        const img = document.createElement("img");
        img.src = frame.path;
        img.alt = `${{currentSection.heading}} at ${{frame.timestamp_str}}`;
        img.addEventListener("click", () => openLightbox(effectiveFrames, idx));
        const stamp = document.createElement("time");
        const badge = frame.frame_type && frame.frame_type !== "other"
          ? `<span class="frame-badge">${{escapeHtml(frame.frame_type)}}</span>` : "";
        stamp.innerHTML = frame.caption
          ? `${{escapeHtml(frame.timestamp_str)}} · ${{escapeHtml(frame.caption)}}${{badge}}`
          : `${{escapeHtml(frame.timestamp_str)}}${{badge}}`;
        card.appendChild(img);
        card.appendChild(stamp);
        if (frame.ocr_text) {{
          const ocr = document.createElement("div");
          ocr.className = isCodeLike(frame.ocr_text) ? "frame-ocr code-ocr" : "frame-ocr";
          ocr.textContent = frame.ocr_text;
          card.appendChild(ocr);
        }}
        gallery.appendChild(card);
      }});

      renderEducationalArtifacts(currentSection);

      renderTranscript();
      if (shouldSeek) seekTo(currentSection.start, false);
    }}

    function renderEducationalArtifacts(section) {{
      let container = document.getElementById("current-edu-artifacts");
      if (!container) {{
        container = document.createElement("div");
        container.id = "current-edu-artifacts";
        container.className = "edu-artifacts";
        const sectionCard = document.querySelector(".section-card");
        if (sectionCard) sectionCard.appendChild(container);
      }}
      container.innerHTML = "";

      const formulas = section.formulas || [];
      const code = section.code_snippets || [];
      const examples = section.examples || [];

      if (!formulas.length && !code.length && !examples.length) {{
        container.hidden = true;
        return;
      }}
      container.hidden = false;

      if (formulas.length) {{
        const block = document.createElement("div");
        block.className = "edu-block formulas";
        const label = document.createElement("div");
        label.className = "edu-label";
        label.textContent = "Formulas";
        block.appendChild(label);
        formulas.forEach(f => {{
          const item = document.createElement("div");
          item.className = "formula-item";
          item.textContent = f;
          block.appendChild(item);
        }});
        container.appendChild(block);
        renderKaTeX(block);
      }}

      if (code.length) {{
        const block = document.createElement("div");
        block.className = "edu-block code";
        const label = document.createElement("div");
        label.className = "edu-label";
        label.style.color = "#a6adc8";
        label.textContent = "Code";
        block.appendChild(label);
        code.forEach(snippet => {{
          const pre = document.createElement("pre");
          pre.textContent = snippet;
          block.appendChild(pre);
        }});
        container.appendChild(block);
      }}

      if (examples.length) {{
        const block = document.createElement("div");
        block.className = "edu-block examples";
        const label = document.createElement("div");
        label.className = "edu-label";
        label.textContent = "Examples";
        block.appendChild(label);
        examples.forEach(ex => {{
          const item = document.createElement("div");
          item.className = "example-item";
          item.textContent = ex;
          block.appendChild(item);
        }});
        container.appendChild(block);
      }}
    }}

    function renderMarkdown(text) {{
      if (typeof marked !== "undefined" && marked.parse) {{
        try {{
          const html = marked.parse(text || "");
          return `<div class="rendered-md">${{html}}</div>`;
        }} catch (e) {{}}
      }}
      return escapeHtml(text || "");
    }}

    function renderKaTeX(element) {{
      if (typeof renderMathInElement === "function") {{
        try {{
          renderMathInElement(element, {{
            delimiters: [
              {{left: "$$", right: "$$", display: true}},
              {{left: "$", right: "$", display: false}},
              {{left: "\\\\(", right: "\\\\)", display: false}},
              {{left: "\\\\[", right: "\\\\]", display: true}},
            ],
            throwOnError: false,
          }});
        }} catch (e) {{}}
      }}
    }}

    function findActiveSectionByTime(seconds, sections = DATA.sections) {{
      if (!Number.isFinite(seconds)) return null;
      for (const section of sections) {{
        const matchesSection = seconds >= section.start && seconds < section.end;
        if (!matchesSection) continue;
        const activeSubsection = findActiveSectionByTime(seconds, section.subsections || []);
        return activeSubsection || section;
      }}
      return null;
    }}

    function buildAnnotatedPoints(section) {{
      const points = section.key_points || [];
      const frames = getEffectiveFrames(section);
      if (!points.length) return [];
      if (!frames.length) return points.map(point => ({{ point, frame: null }}));

      const STOP_WORDS = new Set([
        "the","a","an","is","are","was","were","be","been","being","have","has","had",
        "do","does","did","will","would","shall","should","may","might","must","can",
        "could","to","of","in","for","on","with","at","by","from","as","into","through",
        "during","before","after","above","below","between","out","off","over","under",
        "again","further","then","once","here","there","when","where","why","how","all",
        "each","every","both","few","more","most","other","some","such","no","nor","not",
        "only","own","same","so","than","too","very","just","because","but","and","or",
        "if","while","about","up","it","its","this","that","these","those","what","which",
        "who","whom","they","them","their","we","us","our","you","your","he","him","his",
        "she","her","i","my","me"
      ]);

      function tokenize(text) {{
        if (!text) return [];
        return text.toLowerCase().replace(/[^a-z0-9\\s]/g, " ").split(/\\s+/).filter(w => w.length > 1 && !STOP_WORDS.has(w));
      }}

      function weightedJaccard(tokensA, tokensB) {{
        if (!tokensA.length || !tokensB.length) return 0;
        const weight = w => w.length > 5 ? 2 : 1;
        const bagA = {{}};
        tokensA.forEach(w => {{ bagA[w] = (bagA[w] || 0) + weight(w); }});
        const bagB = {{}};
        tokensB.forEach(w => {{ bagB[w] = (bagB[w] || 0) + weight(w); }});
        const allKeys = new Set([...Object.keys(bagA), ...Object.keys(bagB)]);
        let inter = 0, union = 0;
        allKeys.forEach(k => {{
          inter += Math.min(bagA[k] || 0, bagB[k] || 0);
          union += Math.max(bagA[k] || 0, bagB[k] || 0);
        }});
        return union > 0 ? inter / union : 0;
      }}

      const sectionMid = (section.start + section.end) / 2;
      const sectionSpan = Math.max(section.end - section.start, 1);
      const pointTokens = points.map(p => tokenize(p));
      // Prefer VLM description over transcript caption for matching
      const frameTokens = frames.map(f => tokenize(f.description || f.caption || ""));

      const candidates = [];
      for (let pi = 0; pi < points.length; pi++) {{
        for (let fi = 0; fi < frames.length; fi++) {{
          const sim = weightedJaccard(pointTokens[pi], frameTokens[fi]);
          const proximity = 1 - Math.abs(frames[fi].timestamp - sectionMid) / sectionSpan;
          const cs = frames[fi].content_score || 0;
          let score;
          if (frameTokens[fi].length === 0) {{
            score = 0.05 * Math.max(proximity, 0);
          }} else {{
            score = sim + 0.02 * Math.max(proximity, 0) + 0.01 * cs;
          }}
          candidates.push({{ pi, fi, score }});
        }}
      }}
      candidates.sort((a, b) => b.score - a.score);

      const THRESHOLD = 0.08;
      const usedFrames = new Set();
      const usedPoints = new Set();
      const result = points.map(point => ({{ point, frame: null }}));
      for (const c of candidates) {{
        if (usedPoints.has(c.pi) || usedFrames.has(c.fi)) continue;
        if (c.score < THRESHOLD) break;
        result[c.pi].frame = frames[c.fi];
        usedPoints.add(c.pi);
        usedFrames.add(c.fi);
        if (usedPoints.size === points.length || usedFrames.size === frames.length) break;
      }}
      return result;
    }}

    function getEffectiveFrames(section) {{
      const ownFrames = dedupeFrames(section.frames || []);
      if (!(section.subsections || []).length) {{
        return ownFrames;
      }}
      // Always merge subsection frames for a richer view, deduped by path+timestamp
      return dedupeFrames([
        ...ownFrames,
        ...flattenSubsectionFrames(section.subsections || []),
      ]);
    }}

    function flattenSubsectionFrames(subsections) {{
      const frames = [];
      subsections.forEach(subsection => {{
        frames.push(...(subsection.frames || []));
        if (subsection.subsections && subsection.subsections.length) {{
          frames.push(...flattenSubsectionFrames(subsection.subsections));
        }}
      }});
      return frames;
    }}

    function dedupeFrames(frames) {{
      const seen = new Set();
      return (frames || []).filter(frame => {{
        const key = `${{frame.path}}::${{Math.round((frame.timestamp || 0) * 10)}}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      }});
    }}

    function renderTranscript() {{
      transcriptList.innerHTML = "";
      lastHighlightedStamp = null;
      const lines = transcriptMode === "full" ? DATA.transcript : (currentSection?.transcript || []);
      if (!lines.length) {{
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = transcriptMode === "full"
          ? "No transcript segments are available."
          : "No transcript is available for this section.";
        transcriptList.appendChild(empty);
        return;
      }}
      lines.forEach(line => {{
        const button = document.createElement("button");
        button.type = "button";
        button.className = "transcript-line";
        button.dataset.start = String(line.start);
        button.dataset.end = String(line.end);
        button.innerHTML = `<span class="stamp">${{line.timestamp}}</span><span>${{escapeHtml(line.text)}}</span>`;
        button.addEventListener("click", () => seekTo(line.start, false));
        transcriptList.appendChild(button);
      }});
      syncTranscriptHighlight();
    }}

    function findSection(sectionId, sections) {{
      for (const section of sections) {{
        if (section.id === sectionId) return section;
        const match = findSection(sectionId, section.subsections || []);
        if (match) return match;
      }}
      return null;
    }}

    function escapeHtml(text) {{
      const div = document.createElement("div");
      div.textContent = text ?? "";
      return div.innerHTML;
    }}

    function syncTranscriptHighlight(overrideTime = null) {{
      const video = document.getElementById("source-video");
      const currentTime = overrideTime ?? (video ? (video.currentTime || 0) : 0);
      if (transcriptMode === "section" && Date.now() >= userSelectedSectionUntil) {{
        const activeSection = findActiveSectionByTime(currentTime);
        if (activeSection && activeSection.id !== currentSection?.id) {{
          selectSection(activeSection.id, false);
          return;
        }}
      }}
      const lines = Array.from(transcriptList.querySelectorAll(".transcript-line"));
      if (!lines.length) return;
      let active = null;
      let nearest = null;
      let nearestDistance = Number.POSITIVE_INFINITY;
      for (const line of lines) {{
        const start = Number(line.dataset.start || "0");
        const end = Number(line.dataset.end || String(start + 4));
        const midpoint = start + ((end - start) / 2);
        const isActive = currentTime >= (start - 0.12) && currentTime < (end + 0.12);
        const distance = Math.abs(currentTime - midpoint);
        if (distance < nearestDistance) {{
          nearest = line;
          nearestDistance = distance;
        }}
        line.classList.toggle("active", isActive);
        if (isActive) active = line;
      }}
      if (!active && nearestDistance <= 1.5) {{
        active = nearest;
        active?.classList.add("active");
      }}
      if (active && active.dataset.start !== lastHighlightedStamp) {{
        lastHighlightedStamp = active.dataset.start;
        const listRect = transcriptList.getBoundingClientRect();
        const activeRect = active.getBoundingClientRect();
        const targetTop =
          transcriptList.scrollTop
          + (activeRect.top - listRect.top)
          - (transcriptList.clientHeight / 2)
          + (activeRect.height / 2);
        transcriptList.scrollTo({{
          top: Math.max(0, targetTop),
          behavior: "smooth",
        }});
      }}
    }}

    function stopTranscriptTracking() {{
      if (transcriptTrackingHandle !== null) {{
        cancelAnimationFrame(transcriptTrackingHandle);
        transcriptTrackingHandle = null;
      }}
    }}

    function startTranscriptTracking() {{
      stopTranscriptTracking();
      const tick = () => {{
        const video = document.getElementById("source-video");
        if (!video) return;
        syncTranscriptHighlight();
        if (!video.paused && !video.ended) {{
          transcriptTrackingHandle = requestAnimationFrame(tick);
        }} else {{
          transcriptTrackingHandle = null;
        }}
      }};
      transcriptTrackingHandle = requestAnimationFrame(tick);
    }}

    jumpStart.addEventListener("click", () => currentSection && seekTo(currentSection.start, false));
    jumpEnd.addEventListener("click", () => currentSection && seekTo(Math.max(currentSection.start, currentSection.end - 0.25), false));
    toggleFrames.addEventListener("click", () => {{
      showAnnotatedFrames = !showAnnotatedFrames;
      toggleFrames.classList.toggle("active-toggle", showAnnotatedFrames);
      toggleFrames.title = showAnnotatedFrames ? "Hide explanatory snapshots" : "Show explanatory snapshots";
      toggleFrames.setAttribute("aria-label", toggleFrames.title);
      if (currentSection) selectSection(currentSection.id, false);
    }});
    openNotesHtml.addEventListener("click", () => {{
      if (DATA.notes_html_path) {{
        window.open(DATA.notes_html_path, "_blank", "noopener,noreferrer");
      }}
    }});
    openSource.addEventListener("click", () => {{
      if (DATA.video_url) window.open(DATA.video_url, "_blank", "noopener,noreferrer");
    }});

    tabSection.addEventListener("click", () => {{
      transcriptMode = "section";
      tabSection.classList.add("active");
      tabFull.classList.remove("active");
      renderTranscript();
    }});
    tabFull.addEventListener("click", () => {{
      transcriptMode = "full";
      tabFull.classList.add("active");
      tabSection.classList.remove("active");
      renderTranscript();
    }});

    if (sourceVideo) {{
      sourceVideo.addEventListener("timeupdate", () => syncTranscriptHighlight());
      sourceVideo.addEventListener("loadedmetadata", () => syncTranscriptHighlight());
      sourceVideo.addEventListener("seeking", () => syncTranscriptHighlight());
      sourceVideo.addEventListener("seeked", () => syncTranscriptHighlight());
      sourceVideo.addEventListener("play", startTranscriptTracking);
      sourceVideo.addEventListener("pause", stopTranscriptTracking);
      sourceVideo.addEventListener("ended", stopTranscriptTracking);
    }}

    function appendChatMessage(role, text) {{
      const msg = document.createElement("div");
      msg.className = `chat-msg ${{role}}`;
      msg.textContent = text;
      chatLog.appendChild(msg);
      chatLog.scrollTop = chatLog.scrollHeight;
      if (chatPopupWindow && !chatPopupWindow.closed) {{
        const popupLog = chatPopupWindow.document.getElementById("chat-log");
        if (popupLog) {{
          const popupMsg = chatPopupWindow.document.createElement("div");
          popupMsg.className = `chat-msg ${{role}}`;
          popupMsg.textContent = text;
          popupLog.appendChild(popupMsg);
          popupLog.scrollTop = popupLog.scrollHeight;
        }}
      }}
    }}

    function setChatStatus(text) {{
      chatStatus.textContent = text;
      if (chatPopupWindow && !chatPopupWindow.closed) {{
        const popupStatus = chatPopupWindow.document.getElementById("chat-status");
        if (popupStatus) popupStatus.textContent = text;
      }}
    }}

    function updateChatContextLength() {{
      const historyChars = chatHistory.reduce((total, item) => total + (item.text || "").length, 0);
      const transcriptChars = DATA.transcript.reduce((total, item) => total + (item.text || "").length, 0);
      const draftChars = chatInput?.value?.length || 0;
      const totalChars = transcriptChars + historyChars + draftChars;
      chatContextLength.textContent = `Context: ~${{totalChars.toLocaleString()}} chars`;
      if (chatPopupWindow && !chatPopupWindow.closed) {{
        const popupContext = chatPopupWindow.document.getElementById("chat-context-length");
        if (popupContext) popupContext.textContent = chatContextLength.textContent;
      }}
    }}

    async function submitChatQuestion(question, usingWebSearch) {{
      if (!window.location.protocol.startsWith("http")) {{
        setChatStatus("Use view.sh --host-html to enable transcript-aware local chat.");
        appendChatMessage("assistant", "Hosted mode is required for local chat.");
        return;
      }}

      setChatStatus(
        usingWebSearch ? "Analyzing transcript + searching web..." : "Analyzing transcript..."
      );
      chatSend.disabled = true;
      try {{
        const response = await fetch("/__insightforge/chat", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            question,
            transcript: DATA.transcript,
            history: chatHistory,
            title: DATA.title,
            chat: DATA.chat,
            web_search: usingWebSearch,
          }}),
        }});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Chat request failed");
        appendChatMessage("assistant", payload.answer || "No answer returned.");
        chatHistory.push({{ role: "assistant", text: payload.answer || "No answer returned." }});
        updateChatContextLength();
        setChatStatus(payload.used_web_search ? "Answer ready. Used web search." : "Answer ready.");
      }} catch (error) {{
        appendChatMessage("assistant", `Chat is unavailable: ${{error.message}}`);
        setChatStatus("Chat unavailable.");
      }} finally {{
        chatSend.disabled = false;
        if (chatPopupWindow && !chatPopupWindow.closed) {{
          const popupSend = chatPopupWindow.document.getElementById("chat-send");
          if (popupSend) popupSend.disabled = false;
        }}
      }}
    }}

    function openChatPopup() {{
      if (chatPopupWindow && !chatPopupWindow.closed) {{
        chatPopupWindow.focus();
        return;
      }}
      chatPopupWindow = window.open("", "insightforge-chat", "width=520,height=760");
      if (!chatPopupWindow) return;
      chatPopupWindow.document.write(`
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="utf-8" />
          <title>InsightForge Chat</title>
          <style>
            body {{
              margin: 0;
              padding: 16px;
              font-family: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
              background: #f5f1e8;
              color: #192126;
            }}
            .chat-panel {{
              display: flex;
              flex-direction: column;
              gap: 12px;
              height: calc(100vh - 32px);
              background: rgba(255,255,255,0.92);
              border: 1px solid #d7c7af;
              border-radius: 18px;
              padding: 16px;
            }}
            .chat-log {{
              flex: 1 1 auto;
              min-height: 0;
              overflow: auto;
              display: grid;
              gap: 10px;
            }}
            .chat-msg {{
              padding: 12px 14px;
              border-radius: 14px;
              border: 1px solid #d7c7af;
              background: #fff;
              line-height: 1.55;
              white-space: pre-wrap;
            }}
            .chat-msg.user {{
              border-color: rgba(12,108,102,0.28);
              background: rgba(12,108,102,0.08);
            }}
            textarea {{
              width: 100%;
              min-height: 120px;
              resize: vertical;
              border-radius: 14px;
              border: 1px solid #d7c7af;
              padding: 12px 14px;
              font: inherit;
              background: #fff;
              box-sizing: border-box;
            }}
            .chat-actions {{
              display: flex;
              justify-content: space-between;
              align-items: center;
              gap: 12px;
              flex-wrap: wrap;
            }}
            .chat-options {{
              display: inline-flex;
              align-items: center;
              gap: 8px;
              color: #5f665f;
              font-size: 0.9rem;
            }}
            .chat-context {{
              color: #5f665f;
              font-size: 0.84rem;
              font-family: "IBM Plex Mono", ui-monospace, monospace;
            }}
            .chat-status {{
              color: #5f665f;
              font-size: 0.9rem;
            }}
            button {{
              appearance: none;
              border: 1px solid #d7c7af;
              background: #fff;
              border-radius: 999px;
              padding: 0.6rem 0.9rem;
              font: inherit;
              cursor: pointer;
              color: #192126;
            }}
          </style>
        </head>
        <body>
          <section class="chat-panel">
            <div><strong>InsightForge Chat</strong></div>
            <div class="chat-log" id="chat-log"></div>
            <form id="chat-form">
              <textarea id="chat-input" placeholder="Ask a question about this video..."></textarea>
              <div class="chat-actions">
                <label class="chat-options"><input id="chat-web-search" type="checkbox" /> Enable web search</label>
                <span class="chat-context" id="chat-context-length">Context: 0 chars</span>
                <button id="chat-reset" type="button">Reset</button>
                <span class="chat-status" id="chat-status">Hosted mode enables transcript-aware local chat.</span>
                <button id="chat-send" type="submit">Ask</button>
              </div>
            </form>
          </section>
        </body>
        </html>
      `);
      chatPopupWindow.document.close();
      const popupLog = chatPopupWindow.document.getElementById("chat-log");
      Array.from(chatLog.children).forEach(node => {{
        const copy = chatPopupWindow.document.createElement("div");
        copy.className = node.className;
        copy.textContent = node.textContent;
        popupLog.appendChild(copy);
      }});
      const popupStatus = chatPopupWindow.document.getElementById("chat-status");
      if (popupStatus) popupStatus.textContent = chatStatus.textContent;
      const popupContext = chatPopupWindow.document.getElementById("chat-context-length");
      if (popupContext) popupContext.textContent = chatContextLength.textContent;
      const popupCheckbox = chatPopupWindow.document.getElementById("chat-web-search");
      if (popupCheckbox) popupCheckbox.checked = !!chatWebSearch?.checked;
      const popupReset = chatPopupWindow.document.getElementById("chat-reset");
      popupReset?.addEventListener("click", () => {{
        chatHistory = [];
        chatLog.innerHTML = '<div class="chat-msg">Ask questions about the video. In hosted mode, the chat uses the local model plus the full transcript context.</div>';
        const popupLog = chatPopupWindow.document.getElementById("chat-log");
        if (popupLog) {{
          popupLog.innerHTML = '<div class="chat-msg">Ask questions about the video. In hosted mode, the chat uses the local model plus the full transcript context.</div>';
        }}
        updateChatContextLength();
        setChatStatus("Context reset.");
      }});
      const popupForm = chatPopupWindow.document.getElementById("chat-form");
      popupForm?.addEventListener("submit", async (event) => {{
        event.preventDefault();
        const popupInput = chatPopupWindow.document.getElementById("chat-input");
        const popupQuestion = popupInput?.value.trim();
        if (!popupQuestion) return;
        appendChatMessage("user", popupQuestion);
        chatHistory.push({{ role: "user", text: popupQuestion }});
        popupInput.value = "";
        updateChatContextLength();
        const popupSend = chatPopupWindow.document.getElementById("chat-send");
        if (popupSend) popupSend.disabled = true;
        await submitChatQuestion(popupQuestion, !!popupCheckbox?.checked);
      }});
    }}

    chatForm.addEventListener("submit", async (event) => {{
      event.preventDefault();
      const question = chatInput.value.trim();
      if (!question) return;
      appendChatMessage("user", question);
      chatHistory.push({{ role: "user", text: question }});
      chatInput.value = "";
      updateChatContextLength();
      const usingWebSearch = !!(chatWebSearch && chatWebSearch.checked);
      await submitChatQuestion(question, usingWebSearch);
    }});

    chatPopout?.addEventListener("click", openChatPopup);
    chatReset?.addEventListener("click", () => {{
      chatHistory = [];
      chatLog.innerHTML = '<div class="chat-msg">Ask questions about the video. In hosted mode, the chat uses the local model plus the full transcript context.</div>';
      updateChatContextLength();
      setChatStatus("Context reset.");
      if (chatPopupWindow && !chatPopupWindow.closed) {{
        const popupLog = chatPopupWindow.document.getElementById("chat-log");
        if (popupLog) {{
          popupLog.innerHTML = '<div class="chat-msg">Ask questions about the video. In hosted mode, the chat uses the local model plus the full transcript context.</div>';
        }}
      }}
    }});
    chatInput?.addEventListener("input", updateChatContextLength);

    renderNav();
    const initialSection = (flatSections.find(section => section.is_leaf) || flatSections[0]);
    if (initialSection) selectSection(initialSection.id, false);
    updateChatContextLength();
  </script>
</body>
</html>
"""


def _build_notes_html(data: dict) -> str:
    body = [_render_notes_section(section, level=2) for section in data["sections"]]
    sections_html = "\n".join(body)
    executive = ""
    if data.get("executive_summary"):
        executive = (
            "<section class='notes-block'>"
            "<h2>Executive Summary</h2>"
            f"<p>{_escape_html(data['executive_summary'])}</p>"
            "</section>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_escape_html(data["title"])} - Notes</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css" crossorigin="anonymous">
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js" crossorigin="anonymous"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js" crossorigin="anonymous"
    onload="renderMathInElement(document.body, {{delimiters: [{{left:'$$',right:'$$',display:true}},{{left:'$',right:'$',display:false}}], throwOnError:false}});"></script>
  <style>
    :root {{
      --bg: #f6f1e7;
      --card: #fffdf8;
      --ink: #182228;
      --muted: #627076;
      --accent: #0c6c66;
      --border: #d8ccb9;
    }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #fbf8f2 0%, var(--bg) 100%);
      color: var(--ink);
    }}
    main {{
      max-width: 940px;
      margin: 0 auto;
      padding: 28px 18px 48px;
      display: grid;
      gap: 18px;
    }}
    .hero, .notes-block {{
      background: rgba(255,253,248,0.92);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 22px;
    }}
    .meta {{
      color: var(--muted);
      margin-top: 6px;
    }}
    h1, h2, h3, h4, p {{
      margin: 0;
    }}
    .notes-block {{
      display: grid;
      gap: 12px;
    }}
    .time {{
      color: var(--accent);
      font-family: "IBM Plex Mono", ui-monospace, monospace;
      font-size: 0.88rem;
    }}
    ul {{
      margin: 0;
      padding-left: 1.2rem;
      display: grid;
      gap: 0.55rem;
      line-height: 1.55;
    }}
    .sub {{
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px dashed var(--border);
    }}
    .edu-formulas {{
      background: rgba(12,108,102,0.06);
      border: 1px solid rgba(12,108,102,0.2);
      border-radius: 12px;
      padding: 12px 16px;
      margin-top: 8px;
    }}
    .edu-code {{
      background: #1e1e2e;
      color: #cdd6f4;
      border-radius: 12px;
      padding: 12px 16px;
      margin-top: 8px;
      font-family: "IBM Plex Mono", ui-monospace, monospace;
      font-size: 0.88rem;
      white-space: pre-wrap;
      overflow-x: auto;
    }}
    .edu-examples {{
      background: rgba(217,123,41,0.06);
      border: 1px solid rgba(217,123,41,0.2);
      border-radius: 12px;
      padding: 12px 16px;
      margin-top: 8px;
    }}
    .edu-label {{
      font-size: 0.78rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 6px;
      color: var(--muted);
    }}
    .edu-example-item {{
      padding: 6px 10px;
      border-left: 3px solid rgba(217,123,41,0.4);
      margin: 4px 0;
      line-height: 1.55;
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>{_escape_html(data["title"])}</h1>
      <div class="meta">{_escape_html(data["channel"])} · {_escape_html(data["duration"])}</div>
    </section>
    {executive}
    {sections_html}
  </main>
</body>
</html>
"""


def _render_notes_section(section: dict, level: int) -> str:
    heading = min(max(level, 2), 4)
    points = "".join(f"<li>{_escape_html(point)}</li>" for point in section.get("key_points", []))
    subsections = "".join(_render_notes_subsection(sub, level + 1) for sub in section.get("subsections", []))
    edu = _render_edu_html(section)
    return (
        "<section class='notes-block'>"
        f"<h{heading}>{_escape_html(section['heading'])}</h{heading}>"
        f"<div class='time'>{_escape_html(section['timestamp'])} - {_escape_html(section['timestamp_end'])}</div>"
        f"<p>{_escape_html(section.get('summary') or '')}</p>"
        f"{'<ul>' + points + '</ul>' if points else ''}"
        f"{edu}"
        f"{subsections}"
        "</section>"
    )


def _render_notes_subsection(section: dict, level: int) -> str:
    heading = min(max(level, 3), 5)
    points = "".join(f"<li>{_escape_html(point)}</li>" for point in section.get("key_points", []))
    edu = _render_edu_html(section)
    return (
        "<div class='sub'>"
        f"<h{heading}>{_escape_html(section['heading'])}</h{heading}>"
        f"<div class='time'>{_escape_html(section['timestamp'])} - {_escape_html(section['timestamp_end'])}</div>"
        f"<p>{_escape_html(section.get('summary') or '')}</p>"
        f"{'<ul>' + points + '</ul>' if points else ''}"
        f"{edu}"
        "</div>"
    )


def _render_edu_html(section: dict) -> str:
    """Render educational artifacts (formulas, code, examples) as HTML blocks."""
    parts: list[str] = []

    formulas = section.get("formulas", [])
    if formulas:
        items = "".join(f"<div>{_escape_html(f)}</div>" for f in formulas)
        parts.append(
            f"<div class='edu-formulas'>"
            f"<div class='edu-label'>Formulas</div>"
            f"{items}</div>"
        )

    code = section.get("code_snippets", [])
    if code:
        snippets = "".join(f"<pre>{_escape_html(s)}</pre>" for s in code)
        parts.append(
            f"<div class='edu-code'>"
            f"<div class='edu-label' style='color:#a6adc8'>Code</div>"
            f"{snippets}</div>"
        )

    examples = section.get("examples", [])
    if examples:
        items = "".join(f"<div class='edu-example-item'>{_escape_html(e)}</div>" for e in examples)
        parts.append(
            f"<div class='edu-examples'>"
            f"<div class='edu-label'>Examples</div>"
            f"{items}</div>"
        )

    return "".join(parts)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _rel(path: Optional[Path], base: Path) -> Optional[str]:
    if path is None:
        return None
    return os.path.relpath(Path(path).resolve(), start=base.resolve()).replace(os.sep, "/")


def _format_time(seconds: float) -> str:
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _frame_caption(timestamp: float, transcript: Optional[TranscriptResult]) -> str:
    """Build a concise caption from the transcript segment closest to *timestamp*.

    Strategy: gather a window of segments around the frame timestamp, split into
    sentences, score each by proximity to the timestamp, and return the best 1-2
    sentences (up to 200 chars).
    """
    if transcript is None or not transcript.segments:
        return ""

    import re as _re

    segments = transcript.segments
    closest_index = min(
        range(len(segments)),
        key=lambda index: abs(((segments[index].start + segments[index].end) / 2) - timestamp),
    )
    # Wider window for better sentence candidates
    win_start = max(0, closest_index - 3)
    win_end = min(len(segments), closest_index + 4)
    window = segments[win_start:win_end]
    if not window:
        return ""

    # Assign each segment's midpoint so we can score sentences by proximity
    seg_texts: list[tuple[str, float]] = []
    for seg in window:
        mid = (seg.start + seg.end) / 2
        text = seg.text.strip().replace("\n", " ")
        if text:
            seg_texts.append((text, mid))

    if not seg_texts:
        return ""

    # Split into sentences using a regex that respects abbreviations / decimals
    joined = " ".join(t for t, _ in seg_texts)
    avg_time = sum(m for _, m in seg_texts) / len(seg_texts)
    sentences = _re.split(r'(?<=[.!?])\s+(?=[A-Z])', joined)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

    if not sentences:
        # Fallback: use the raw joined text
        if len(joined) > 200:
            joined = joined[:197].rstrip() + "..."
        return joined

    # Score sentences: prefer those whose words appear in segments closest to timestamp
    def _score(sentence: str) -> float:
        sentence_lower = sentence.lower()
        best_proximity = 0.0
        for text, mid in seg_texts:
            # Check word overlap between sentence and segment
            overlap = len(set(sentence_lower.split()) & set(text.lower().split()))
            if overlap > 0:
                proximity = 1.0 / (1.0 + abs(mid - timestamp))
                best_proximity = max(best_proximity, proximity * overlap)
        return best_proximity

    ranked = sorted(sentences, key=_score, reverse=True)

    # Take the best sentence; add a second only if it fits within 200 chars
    result = ranked[0]
    if len(ranked) > 1:
        candidate = result + " " + ranked[1]
        if len(candidate) <= 200:
            result = candidate

    if not result.endswith((".", "!", "?")):
        result += "."
    if len(result) > 200:
        result = result[:197].rstrip() + "..."
    return result
