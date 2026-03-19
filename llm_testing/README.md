# InsightForge LLM Testing

Benchmark scripts for testing and comparing inference servers used by InsightForge.

## Quick Start

```bash
# Run all benchmarks interactively
python3.11 llm_testing/scripts/run_all.py

# Run individual benchmarks
python3.11 llm_testing/scripts/bench_vlm.py      # Vision models
python3.11 llm_testing/scripts/bench_llm.py      # Text models
python3.11 llm_testing/scripts/bench_whisper.py   # Whisper STT

# Non-interactive (all defaults)
python3.11 llm_testing/scripts/run_all.py --non-interactive
```

## What Each Script Tests

### bench_vlm.py — Vision Language Model

- **Endpoint compatibility**: Verifies `/v1/models` and `/v1/chat/completions` (with image) work
- **Batch size scaling**: Measures per-frame cost at batch sizes 1-12
- **Concurrency scaling**: Tests if the server benefits from parallel requests

Servers: LMStudio (`:1234`), Ollama (`:11434`), MLX (`:8080`)

### bench_llm.py — Text LLM

- **Endpoint compatibility**: Tests Ollama `/api/generate` + `/api/tags`, or OpenAI `/v1/chat/completions`
- **Realistic prompts**: Runs InsightForge's actual importance scoring and note synthesis prompts
- **Concurrency scaling**: Throughput at 1-8 parallel requests
- **Thinking model detection**: Flags models that use chain-of-thought (like GLM-4-flash)

Servers: Ollama (`:11434`), LMStudio (`:1234`), MLX (`:8080`)

### bench_whisper.py — Speech-to-Text

- **Model loading**: Time to load different model sizes
- **Sequential vs batched**: Compares `WhisperModel.transcribe()` vs `BatchedInferencePipeline`
- **Batch size scaling**: Tests batch sizes 1-32 for `BatchedInferencePipeline`

```bash
# Test with specific audio file
python3.11 llm_testing/scripts/bench_whisper.py --audio path/to/video.mp4

# Test longer duration
python3.11 llm_testing/scripts/bench_whisper.py --duration 120
```

## Adding New Servers

Edit the `SERVERS` dict in each script. All servers must expose an OpenAI-compatible
`/v1/chat/completions` endpoint (LMStudio, MLX, vLLM, etc.) or Ollama's `/api/generate`.

Example for a new MLX server:
```python
"mlx": {
    "name": "MLX",
    "base_url": "http://localhost:8080/v1",
    "api_key": "mlx",
    "default_model": "mlx-community/Qwen2.5-VL-7B-Instruct-4bit",
}
```
