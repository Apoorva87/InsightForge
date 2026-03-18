"""InsightForge CLI — entry point for the `insightforge` command."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="insightforge",
    help="Local-first YouTube Knowledge Extractor — convert videos to structured notes.",
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)


@app.command("process")
def process(
    youtube_url: str = typer.Argument(..., help="YouTube video URL to process"),
    mode: str = typer.Option("local", "--mode", "-m", help="LLM mode: local | api"),
    detail: str = typer.Option("high", "--detail", "-d", help="Output detail: high | low"),
    frames: str = typer.Option("on", "--frames", help="Frame extraction: on | off"),
    audio: Optional[float] = typer.Option(None, "--audio", help="Audio summary verbosity: 0.0 (exec summary) to 1.0 (full transcript). Omit to skip."),
    output_dir: Path = typer.Option(Path("./output"), "--output-dir", "-o", help="Output directory"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config YAML"),
    model: Optional[str] = typer.Option(None, "--model", help="Override LLM model name"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable DEBUG logging"),
) -> None:
    """Process a YouTube URL and produce structured Markdown notes."""
    from insightforge.models.video import VideoJob
    from insightforge.pipeline import run as pipeline_run, PipelineError

    if verbose:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)

    job = VideoJob(
        url=youtube_url,
        mode=mode,
        detail=detail,
        frames_enabled=(frames.lower() == "on"),
        audio_level=audio,
        output_dir=output_dir,
        config_path=config,
        model_override=model,
    )

    try:
        result = pipeline_run(job)
    except PipelineError as exc:
        err_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        err_console.print("\n[yellow]Interrupted.[/yellow]")
        raise typer.Exit(code=130)

    console.print(f"\n[bold green]Done![/bold green] Notes written to [cyan]{result.notes_path}[/cyan]")
    if result.frames_dir:
        frame_count = len(list(result.frames_dir.iterdir())) if result.frames_dir.exists() else 0
        console.print(f"Frames: [cyan]{result.frames_dir}[/cyan] ({frame_count} images)")
    if result.audio_path and result.audio_path.exists():
        console.print(f"Audio: [cyan]{result.audio_path}[/cyan]")
    console.print(f"Metadata: [cyan]{result.metadata_path}[/cyan]")


@app.command("check")
def check() -> None:
    """Check that all required dependencies are available."""
    table = Table(title="InsightForge Dependency Check", show_header=True)
    table.add_column("Dependency", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    checks = [
        ("ffmpeg", _check_binary("ffmpeg"), "Required for frame extraction"),
        ("yt-dlp", _check_binary("yt-dlp"), "Required for video download"),
        ("ollama", _check_ollama(), "Required for local LLM (mode=local)"),
        ("faster-whisper", _check_python_pkg("faster_whisper"), "Required for local transcription"),
        ("anthropic SDK", _check_python_pkg("anthropic"), "Required for mode=api"),
        ("openai SDK", _check_python_pkg("openai"), "Required for LMStudio support"),
        ("tiktoken", _check_python_pkg("tiktoken"), "Recommended for accurate token counts"),
    ]

    all_ok = True
    for name, ok, detail in checks:
        status = "[green]OK[/green]" if ok else "[red]MISSING[/red]"
        table.add_row(name, status, detail)
        if not ok:
            all_ok = False

    console.print(table)

    if not all_ok:
        console.print("\n[yellow]Some dependencies are missing. See README for installation instructions.[/yellow]")
        raise typer.Exit(code=1)
    else:
        console.print("\n[bold green]All dependencies found.[/bold green]")


def _check_binary(name: str) -> bool:
    return shutil.which(name) is not None


def _check_python_pkg(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _check_ollama() -> bool:
    try:
        import httpx
        response = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        return response.status_code == 200
    except Exception:
        return False


def main() -> None:
    app()


if __name__ == "__main__":
    main()
