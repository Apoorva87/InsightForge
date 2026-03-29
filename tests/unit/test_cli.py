"""Unit tests for CLI behavior."""

from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from insightforge import cli


runner = CliRunner()


def test_process_verbose_forces_debug_logging(monkeypatch, tmp_path) -> None:
    captured_job = {}

    def fake_pipeline_run(job):
        captured_job["job"] = job
        return SimpleNamespace(
            notes_path=tmp_path / "notes.md",
            metadata_path=tmp_path / "metadata.json",
            frames_dir=None,
            audio_path=None,
            html_path=None,
        )

    monkeypatch.setattr("insightforge.pipeline.run", fake_pipeline_run)

    result = runner.invoke(
        cli.app,
        ["process", "https://www.youtube.com/watch?v=test123", "--verbose"],
    )

    assert result.exit_code == 0
    assert captured_job["job"].verbose is True
