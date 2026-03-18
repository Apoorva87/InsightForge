"""Unit tests for Stage 7 — LLM Processing."""

from __future__ import annotations

import json

import pytest

from insightforge.models.output import NoteSection
from insightforge.stages.llm_processing import (
    _explanation_style_guidance,
    _frame_candidates,
    _fallback_section_data,
    _invalid_executive_summary_data,
    _parse_json_response,
    _section_frames,
    generate_executive_summary,
    run,
)


class TestLLMProcessingRun:
    def test_returns_one_section_per_chunk(self, sample_scored_chunk, mock_llm_note):
        result = run(scored_chunks=[sample_scored_chunk], llm=mock_llm_note)
        assert len(result) == 1

    def test_section_has_heading(self, sample_scored_chunk, mock_llm_note):
        result = run(scored_chunks=[sample_scored_chunk], llm=mock_llm_note)
        assert result[0].heading != ""

    def test_section_has_key_points(self, sample_scored_chunk, mock_llm_note):
        result = run(scored_chunks=[sample_scored_chunk], llm=mock_llm_note)
        assert isinstance(result[0].key_points, list)

    def test_section_frames_attached(self, sample_scored_chunk, mock_llm_note, sample_frame_set):
        result = run(
            scored_chunks=[sample_scored_chunk],
            llm=mock_llm_note,
            frame_set=sample_frame_set,
        )
        # Frame at 6.0s is within 15s of chunk midpoint 6.0s
        assert len(result[0].frames) >= 1

    def test_fallback_on_bad_json(self, sample_scored_chunk):
        from tests.conftest import MockLLMProvider
        bad_llm = MockLLMProvider(response_text="not json at all !!!")
        result = run(scored_chunks=[sample_scored_chunk], llm=bad_llm)
        assert len(result) == 1
        assert result[0].heading != ""

    def test_hierarchical_run_creates_nested_sections_for_large_topic(self, sample_chunk_batch):
        from insightforge.llm.base import LLMProvider, LLMRequest, LLMResponse
        from insightforge.models.scoring import ScoredChunk

        chunk_a = sample_chunk_batch.chunks[0]
        chunk_b = sample_chunk_batch.chunks[1]
        chunk_c = chunk_b.model_copy(update={"chunk_id": "chunk_0002", "start": 40.0, "end": 55.0})
        chunk_d = chunk_b.model_copy(update={"chunk_id": "chunk_0003", "start": 55.0, "end": 70.0})

        scored_chunks = []
        for chunk in [chunk_a, chunk_b, chunk_c, chunk_d]:
            sc = ScoredChunk(chunk=chunk, llm_score=0.8, visual_score=0.0)
            sc.compute_composite()
            scored_chunks.append(sc)

        class SequenceLLM(LLMProvider):
            def __init__(self):
                self.calls = 0

            @property
            def name(self) -> str:
                return "sequence"

            def complete(self, request: LLMRequest) -> LLMResponse:
                self.calls += 1
                if '"main_idea"' in request.prompt:
                    idx = self.calls
                    payload = {
                        "heading": f"Chunk {idx}",
                        "main_idea": f"Chunk {idx} explains one part of the topic.",
                        "key_points": [f"Point {idx}a", f"Point {idx}b"],
                        "keywords": ["python", "decorators", f"topic{idx}"],
                        "transition": "continue",
                    }
                elif "Sub-section summaries" in request.prompt:
                    payload = {
                        "heading": "Decorator Patterns",
                        "summary": "This topic groups several related decorator ideas.",
                        "key_points": ["It builds progressively", "Each part adds detail"],
                    }
                else:
                    payload = {
                        "heading": f"Subsection {self.calls}",
                        "summary": "This subsection condenses several chunk summaries.",
                        "key_points": ["One bounded idea", "Uses compressed inputs"],
                    }
                return LLMResponse(
                    text=json.dumps(payload),
                    model="mock-model",
                    provider="sequence",
                )

        result = run(
            scored_chunks=scored_chunks,
            llm=SequenceLLM(),
            hierarchical=True,
            max_chunks_per_topic=4,
            max_chunk_summaries_per_subsection=2,
            boundary_threshold=1.0,
        )

        assert len(result) == 1
        assert len(result[0].subsections) == 2
        assert all(sub.is_leaf for sub in result[0].subsections)

    def test_explanation_style_is_included_in_leaf_prompt(self, sample_scored_chunk):
        from insightforge.llm.base import LLMProvider, LLMRequest, LLMResponse

        class CapturingLLM(LLMProvider):
            def __init__(self):
                self.prompts: list[str] = []

            @property
            def name(self) -> str:
                return "capturing"

            def complete(self, request: LLMRequest) -> LLMResponse:
                self.prompts.append(request.prompt)
                return LLMResponse(
                    text=json.dumps(
                        {
                            "heading": "Attention Basics",
                            "summary": "A clear teaching-oriented explanation.",
                            "key_points": ["Point one", "Point two"],
                        }
                    ),
                    model="mock-model",
                    provider="capturing",
                )

        llm = CapturingLLM()
        run(
            scored_chunks=[sample_scored_chunk],
            llm=llm,
            hierarchical=False,
            explanation_style="educational",
        )

        assert llm.prompts
        assert "Write like a strong teacher." in llm.prompts[0]
        assert "Situate this section within the broader flow of the video." in llm.prompts[0]

    def test_hierarchical_prompt_includes_neighbor_context(self, sample_chunk_batch):
        from insightforge.llm.base import LLMProvider, LLMRequest, LLMResponse
        from insightforge.models.scoring import ScoredChunk

        chunk_a = sample_chunk_batch.chunks[0]
        chunk_b = sample_chunk_batch.chunks[1]
        scored_chunks = []
        for chunk in [chunk_a, chunk_b]:
            sc = ScoredChunk(chunk=chunk, llm_score=0.8, visual_score=0.0)
            sc.compute_composite()
            scored_chunks.append(sc)

        class CapturingSequenceLLM(LLMProvider):
            def __init__(self):
                self.prompts: list[str] = []

            @property
            def name(self) -> str:
                return "capturing-sequence"

            def complete(self, request: LLMRequest) -> LLMResponse:
                self.prompts.append(request.prompt)
                if '"main_idea"' in request.prompt:
                    payload = {
                        "heading": "Chunk",
                        "main_idea": "Chunk explains one part of the topic.",
                        "key_points": ["Point A", "Point B"],
                        "keywords": ["python", "decorators"],
                        "transition": "continue",
                    }
                else:
                    payload = {
                        "heading": "Combined Topic",
                        "summary": "This section builds on the previous idea and prepares for what comes next.",
                        "key_points": ["Builds context", "Maintains continuity"],
                    }
                return LLMResponse(
                    text=json.dumps(payload),
                    model="mock-model",
                    provider="capturing-sequence",
                )

        llm = CapturingSequenceLLM()
        run(
            scored_chunks=scored_chunks,
            llm=llm,
            hierarchical=True,
            max_chunks_per_topic=1,
            boundary_threshold=0.0,
        )

        topic_prompts = [prompt for prompt in llm.prompts if "Coherence guidance:" in prompt and "Chunk summaries:" in prompt]
        assert topic_prompts
        assert "Upcoming context:" in topic_prompts[0] or "Previous context:" in topic_prompts[1]

class TestExplanationStyleGuidance:
    def test_unknown_style_falls_back_to_default_guidance(self):
        assert (
            _explanation_style_guidance("something-else")
            == _explanation_style_guidance("well_explained")
        )

    def test_known_styles_return_nonempty(self):
        for style in ("concise", "well_explained", "educational"):
            assert len(_explanation_style_guidance(style)) > 0

    def test_hyphenated_style_normalized(self):
        assert _explanation_style_guidance("well-explained") == _explanation_style_guidance("well_explained")

    def test_none_style_uses_default(self):
        assert _explanation_style_guidance(None) == _explanation_style_guidance("well_explained")


class TestParseJsonResponse:
    def test_parses_clean_json(self):
        data = _parse_json_response('{"heading": "Test", "summary": "Sum", "key_points": []}')
        assert data["heading"] == "Test"

    def test_strips_markdown_fences(self):
        text = "```json\n{\"heading\": \"Test\"}\n```"
        data = _parse_json_response(text)
        assert data["heading"] == "Test"

    def test_raises_on_invalid(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_json_response("not json")


class TestExecutiveSummary:
    def test_placeholder_exec_summary_triggers_fallback(self, sample_note_section):
        from tests.conftest import MockLLMProvider

        llm = MockLLMProvider(response_text='{"executive_summary":"...","highlights":["..."]}')
        summary = generate_executive_summary(
            sections=[sample_note_section],
            llm=llm,
            title="Test Title",
            channel="Test Channel",
        )

        assert "This video covers" in summary

    def test_invalid_exec_summary_detector(self):
        assert _invalid_executive_summary_data(
            {"executive_summary": "...", "highlights": ["..."]}
        ) is True


class TestFrameSelection:
    def test_frame_candidates_prioritize_diverse_candidates(self, tmp_path):
        from insightforge.models.frame import Frame, FrameSet

        paths = []
        for i in range(5):
            path = tmp_path / f"frame_{i}.jpg"
            path.write_bytes(b"x" * (100 + i))
            paths.append(path)

        frame_set = FrameSet(
            frames=[
                Frame(frame_id="f0", timestamp=10.0, path=paths[0], content_score=0.9),
                Frame(frame_id="f1", timestamp=11.0, path=paths[1], content_score=0.85),
                Frame(frame_id="f2", timestamp=15.0, path=paths[2], content_score=0.7),
                Frame(frame_id="f3", timestamp=20.0, path=paths[3], content_score=0.8),
                Frame(frame_id="f4", timestamp=24.0, path=paths[4], content_score=0.6),
            ]
        )

        candidates = _frame_candidates(frame_set, start=8.0, end=26.0, max_candidates=3)

        assert len(candidates) <= 3
        assert all(abs(a.timestamp - b.timestamp) >= 4.0 for a, b in zip(candidates, candidates[1:]))

    def test_section_frames_uses_vision_ranking_when_available(self, tmp_path):
        from insightforge.models.frame import Frame, FrameSet

        paths = []
        for i in range(3):
            path = tmp_path / f"rank_{i}.jpg"
            path.write_bytes(b"x" * (100 + i))
            paths.append(path)

        frames = [
            Frame(frame_id="f0", timestamp=10.0, path=paths[0], content_score=0.6),
            Frame(frame_id="f1", timestamp=15.0, path=paths[1], content_score=0.9),
            Frame(frame_id="f2", timestamp=22.0, path=paths[2], content_score=0.7),
        ]
        frame_set = FrameSet(frames=frames)

        class MockVisionReranker:
            def rank_frames(self, **kwargs):
                return ["frame_1", "frame_0"]

        selected = _section_frames(
            frame_set=frame_set,
            start=8.0,
            end=24.0,
            heading="Section",
            summary="Summary",
            key_points=["Point"],
            vision_reranker=MockVisionReranker(),
            keep=2,
            max_candidates=3,
        )

        assert [frame.timestamp for frame in selected] == [10.0, 15.0]
