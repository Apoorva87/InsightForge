#!/usr/bin/env bash
# InsightForge — process a YouTube video into structured Markdown notes.
#
# Usage:
#   ./run.sh <youtube_url>
#   ./run.sh <youtube_url> --detail low --frames off
#   ./run.sh <youtube_url> --output-dir ./my-notes --verbose
#   ./run.sh <youtube_url> --html on
#   ./run.sh <youtube_url> --profile educational
#   ./run.sh <youtube_url> --profile entertainment --frame-rerank heuristic
#   ./run.sh --audio-from ./output/<video_dir> --audio 0.5
#
# Options (all optional, passed through to insightforge process):
#   --mode local|api        LLM mode (default: local)
#   --detail high|low       Output detail level (default: high)
#   --frames on|off         Enable frame extraction (default: on)
#   --html on|off           Export interactive HTML viewer (default: off)
#   --profile NAME          Saved preset: educational | entertainment (default: educational)
#   --frame-rerank MODE     vlm | heuristic (default: profile-based)
#   --audio FLOAT           Audio summary verbosity: 0.0 to 1.0
#   --audio-from PATH       Generate audio later from an existing output dir
#   --output-dir PATH       Output directory (default: ./output)
#   --config PATH           Custom config YAML
#   --model NAME            Override LLM model
#   --verbose               Enable DEBUG logging
#
set -euo pipefail

# ---- Colour helpers ----
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PROFILE="educational"
FRAME_RERANK_MODE=""
USER_CONFIG=""
FORWARDED_ARGS=()
MERGED_CONFIG=""
AUDIO_FROM=""
AUDIO_LEVEL=""

print_help() {
    echo -e "${BOLD}InsightForge${NC} — YouTube Knowledge Extractor"
    echo ""
    echo -e "Usage: ${CYAN}./run.sh <youtube_url> [options]${NC}"
    echo -e "       ${CYAN}./run.sh --audio-from <output_dir> [--audio 0.5]${NC}"
    echo -e "       ${CYAN}./run.sh --check${NC}"
    echo ""
    echo "Options:"
    echo "  -h, --help              Show this help message"
    echo "  --mode local|api        LLM mode (default: local)"
    echo "  --detail high|low       Detail level (default: high)"
    echo "  --frames on|off         Frame extraction (default: on)"
    echo "  --html on|off           Export interactive HTML viewer (default: off)"
    echo "  --profile NAME          Saved preset: educational | entertainment (default: educational)"
    echo "  --frame-rerank MODE     Frame selection: vlm | heuristic (default: profile-based)"
    echo "  --audio FLOAT           Audio summary verbosity: 0.0 to 1.0"
    echo "  --audio-from PATH       Generate audio from an existing output directory"
    echo "  --output-dir PATH       Output directory (default: ./output)"
    echo "  --config PATH           Custom config YAML"
    echo "  --model NAME            Override LLM model name"
    echo "  --verbose               Enable DEBUG logging"
    echo ""
    echo "Preset guidance:"
    echo "  educational   Best for lectures, tutorials, technical explainers."
    echo "                Default profile. Uses denser chunking, more overlap, 2 frames per section,"
    echo "                educational note style, and defaults to VLM frame reranking."
    echo "  entertainment Best for podcasts, commentary, stories, interviews."
    echo "                Uses broader sections, fewer frames, more selective highlights,"
    echo "                concise note style, and defaults to heuristic frame reranking."
    echo ""
    echo "Frame reranking guidance:"
    echo "  vlm           Use local vision model for better explanatory frame choice."
    echo "                This is the default with the educational profile."
    echo "  heuristic     Skip the local VLM and use fast heuristics only."
    echo "                This is the default with the entertainment profile."
    echo ""
    echo "Audio guidance:"
    echo "  Use --audio during processing if you want audio in the same pipeline run."
    echo "  Use --audio-from later if notes/transcript already exist and you only want audio."
    echo ""
    echo "HTML guidance:"
    echo "  Use --html on to export viewer/index.html with section browsing, transcript pane,"
    echo "  inline frame snapshots, and local video seeking from transcript clicks."
    echo ""
    echo "Examples:"
    echo "  ./run.sh 'https://www.youtube.com/watch?v=VIDEO_ID'"
    echo "  ./run.sh 'https://youtu.be/VIDEO_ID' --detail low --frames off"
    echo "  ./run.sh 'https://youtu.be/VIDEO_ID' --html on"
    echo "  ./run.sh 'https://youtu.be/VIDEO_ID' --profile educational"
    echo "  ./run.sh 'https://youtu.be/VIDEO_ID' --profile entertainment --frame-rerank heuristic"
    echo "  ./run.sh --audio-from ./output/MyVideo_abc123 --audio 0.5"
    echo "  ./run.sh 'https://www.youtube.com/watch?v=VIDEO_ID' --output-dir ./notes --verbose"
    echo ""
    echo "Quick check:  ./run.sh --check"
}

# ---- Find Python ----
if command -v python3.11 &>/dev/null; then
    PYTHON=python3.11
elif command -v python3 &>/dev/null; then
    PYTHON=python3
else
    echo -e "${RED}Error: Python 3 not found. Install Python 3.10+ first.${NC}"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ---- Handle help/check before URL parsing ----
if [[ $# -eq 0 ]]; then
    print_help
    exit 1
fi

if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    print_help
    exit 0
fi

if [[ "$1" == "--check" ]]; then
    echo -e "${BOLD}Running dependency check...${NC}"
    $PYTHON -m insightforge.cli check
    exit $?
fi

if [[ "$1" == "--audio-from" ]]; then
    if [[ $# -lt 2 ]]; then
        echo -e "${RED}Error: --audio-from requires a directory path.${NC}"
        exit 1
    fi
    AUDIO_FROM="$2"
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --audio)
                AUDIO_LEVEL="$2"
                shift 2
                ;;
            *)
                echo -e "${RED}Unknown option for audio mode: $1${NC}"
                exit 1
                ;;
        esac
    done
    if [[ -z "$AUDIO_LEVEL" ]]; then
        AUDIO_LEVEL="0.5"
    fi
    echo -e "${BOLD}InsightForge${NC} audio summary from: ${CYAN}${AUDIO_FROM}${NC}"
    echo "  Target verbosity: ${AUDIO_LEVEL}"
    "$PYTHON" -m insightforge.cli audio-summary "$AUDIO_FROM" --audio "$AUDIO_LEVEL"
    exit $?
fi

# ---- Check for URL argument ----
if [[ "$1" == --* || "$1" == -* ]]; then
    echo -e "${RED}Unknown option: $1${NC}"
    echo ""
    print_help
    exit 1
fi

URL="$1"
shift

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            PROFILE="$2"
            shift 2
            ;;
        --frame-rerank)
            FRAME_RERANK_MODE="$2"
            shift 2
            ;;
        --audio)
            AUDIO_LEVEL="$2"
            FORWARDED_ARGS+=("$1" "$2")
            shift 2
            ;;
        --config)
            USER_CONFIG="$2"
            shift 2
            ;;
        *)
            FORWARDED_ARGS+=("$1")
            shift
            ;;
    esac
done

if [[ -n "$PROFILE" ]]; then
    case "$PROFILE" in
        educational|entertainment) ;;
        *)
            echo -e "${RED}Unknown profile: ${PROFILE}${NC}"
            echo "Use one of: educational, entertainment"
            exit 1
            ;;
    esac
fi

if [[ -n "$FRAME_RERANK_MODE" ]]; then
    case "$FRAME_RERANK_MODE" in
        vlm|heuristic) ;;
        *)
            echo -e "${RED}Unknown frame rerank mode: ${FRAME_RERANK_MODE}${NC}"
            echo "Use one of: vlm, heuristic"
            exit 1
            ;;
    esac
fi

if [[ -z "$FRAME_RERANK_MODE" ]]; then
    if [[ "$PROFILE" == "entertainment" ]]; then
        FRAME_RERANK_MODE="heuristic"
    else
        FRAME_RERANK_MODE="vlm"
    fi
fi

cleanup() {
    if [[ -n "${MERGED_CONFIG}" && -f "${MERGED_CONFIG}" ]]; then
        rm -f "${MERGED_CONFIG}"
    fi
}
trap cleanup EXIT

if [[ -n "$PROFILE" || -n "$USER_CONFIG" ]]; then
    MERGED_CONFIG="$(mktemp /tmp/insightforge_run_config.XXXXXX)"
    MERGED_CONFIG="${MERGED_CONFIG}.yaml"
    PRESET_CONFIG=""
    if [[ -n "$PROFILE" ]]; then
        PRESET_CONFIG="$SCRIPT_DIR/config/presets/${PROFILE}.yaml"
    fi
    export INSIGHTFORGE_PRESET_CONFIG="$PRESET_CONFIG"
    export INSIGHTFORGE_USER_CONFIG="$USER_CONFIG"
    export INSIGHTFORGE_MERGED_CONFIG="$MERGED_CONFIG"
    "$PYTHON" - <<PY
import os
from pathlib import Path
import yaml

def deep_merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

config = {}
for maybe_path in [
    os.environ.get("INSIGHTFORGE_PRESET_CONFIG", ""),
    os.environ.get("INSIGHTFORGE_USER_CONFIG", ""),
]:
    if not maybe_path:
        continue
    path = Path(maybe_path)
    if path.exists():
        with path.open() as f:
            config = deep_merge(config, yaml.safe_load(f) or {})

with Path(os.environ["INSIGHTFORGE_MERGED_CONFIG"]).open("w") as f:
    yaml.safe_dump(config, f, sort_keys=False)
PY
    unset INSIGHTFORGE_PRESET_CONFIG
    unset INSIGHTFORGE_USER_CONFIG
    unset INSIGHTFORGE_MERGED_CONFIG
    if [[ -s "$MERGED_CONFIG" ]]; then
        FORWARDED_ARGS+=("--config" "$MERGED_CONFIG")
    fi
fi

if [[ "$FRAME_RERANK_MODE" == "heuristic" ]]; then
    export INSIGHTFORGE_FRAME_RERANK=heuristic
else
    export INSIGHTFORGE_FRAME_RERANK=vlm
fi

echo -e "${BOLD}InsightForge${NC} processing: ${CYAN}${URL}${NC}"
echo -e "Profile: ${GREEN}${PROFILE}${NC}"
echo -e "Frame reranking: ${GREEN}${FRAME_RERANK_MODE}${NC}"
echo -e "${BOLD}Tentative Timeline${NC}"
echo "  Ingestion + metadata: ~15-45s"
echo "  Transcript: ~1-6 min depending on caption availability and video length"
echo "  Chunk scoring + note generation: ~1-6 min depending on model speed and section count"
echo "  Frames + clips + formatting: ~30-120s"
echo "  Remaining time will be re-estimated in the pipeline logs after ingestion."
echo ""

# Run the pipeline, passing any remaining arguments through
$PYTHON -m insightforge.cli process "$URL" "${FORWARDED_ARGS[@]}"
status=$?

echo ""
printf "%b\n" "${GREEN}${BOLD}Complete!${NC} Check the output directory for notes.md, transcript.txt, and frames/"
exit "$status"
