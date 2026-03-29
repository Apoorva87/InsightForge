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

## Better Defaults For Slow Local Models

Local models often exceed short fixed timeouts, especially for vision requests,
larger prompts, or multi-request concurrency tests. Use the timeout flags to
reduce false failures and trim the test matrix while tuning.

```bash
# LLM benchmark with longer prompt timeout and a smaller concurrency sweep
python3.11 llm_testing/scripts/bench_llm.py \
  --prompt-timeout 300 \
  --request-timeout 60 \
  --concurrency-levels 1,2,4

# VLM benchmark with more generous image timeout and smaller batch sweep
python3.11 llm_testing/scripts/bench_vlm.py \
  --vision-timeout 300 \
  --text-timeout 60 \
  --batch-sizes 1,2,4,6 \
  --concurrency-levels 1,2,4
```

## How To Read Concurrency Results

- `Throughput`: completed requests per second at that concurrency level.
- `Speedup`: throughput relative to the `concurrency=1` baseline.
- `Eff.`: scaling efficiency, computed as `speedup / concurrency`.
- `Lat x1`: average latency relative to the single-request baseline.

Example: if concurrency `4` reports `speedup=2.8x`, the scaling efficiency is
`2.8 / 4 = 70%`.

## Interactive Menu Notes

- `all` means every discovered server or test in that menu.
- Comma-separated server keys look like `ollama,lmstudio` or `lmstudio,mlx`.
- Numbered test selections use the indices shown in that prompt.
- Pressing Enter chooses the default noted by the prompt.

## What Each Script Tests

### bench_vlm.py — Vision Language Model

- **Endpoint compatibility**: Verifies `/v1/models` and `/v1/chat/completions` (with image) work
- **Batch size scaling**: Measures per-frame cost at batch sizes 1-12
- **Concurrency scaling**: Tests if the server benefits from parallel requests
- **Scaling efficiency**: Speedup divided by concurrency, using the 1-request run as baseline

Servers: LMStudio (`:1234`), Ollama (`:11434`), MLX (`:8080`)

### bench_llm.py — Text LLM

- **Endpoint compatibility**: Tests Ollama `/api/generate` + `/api/tags`, or OpenAI `/v1/chat/completions`
- **Realistic prompts**: Runs InsightForge's actual importance scoring and note synthesis prompts
- **Concurrency scaling**: Throughput at 1-8 parallel requests
- **Scaling efficiency**: Speedup divided by concurrency, using the 1-request run as baseline
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

## MLX Setup

Install MLX tooling into the project virtualenv:

```bash
../.venv/bin/pip install -U mlx mlx-lm huggingface_hub
```

Start a text model server:

```bash
../.venv/bin/python -m mlx_lm server \
  --model llm_testing/models/mlx-community/Qwen2.5-7B-Instruct-4bit \
  --host 127.0.0.1 \
  --port 8080
```

Start a vision-language server:

```bash
../.venv/bin/python -m mlx_lm server \
  --model llm_testing/models/mlx-community/Qwen2.5-VL-7B-Instruct-4bit \
  --host 127.0.0.1 \
  --port 8080
```

The local model cache lives under `llm_testing/models/`. If a model is gated on
Hugging Face, run `hf auth login` first.

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
