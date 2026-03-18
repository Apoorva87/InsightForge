#!/usr/bin/env bash
# InsightForge — process a YouTube video into structured Markdown notes.
#
# Usage:
#   ./run.sh <youtube_url>
#   ./run.sh <youtube_url> --detail low --frames off
#   ./run.sh <youtube_url> --output-dir ./my-notes --verbose
#
# Options (all optional, passed through to insightforge process):
#   --mode local|api        LLM mode (default: local)
#   --detail high|low       Output detail level (default: high)
#   --frames on|off         Enable frame extraction (default: on)
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

# ---- Find Python ----
if command -v python3.11 &>/dev/null; then
    PYTHON=python3.11
elif command -v python3 &>/dev/null; then
    PYTHON=python3
else
    echo -e "${RED}Error: Python 3 not found. Install Python 3.10+ first.${NC}"
    exit 1
fi

# ---- Check for URL argument ----
if [ $# -lt 1 ] || [[ "$1" == --* ]]; then
    echo -e "${BOLD}InsightForge${NC} — YouTube Knowledge Extractor"
    echo ""
    echo -e "Usage: ${CYAN}./run.sh <youtube_url> [options]${NC}"
    echo ""
    echo "Options:"
    echo "  --mode local|api        LLM mode (default: local)"
    echo "  --detail high|low       Detail level (default: high)"
    echo "  --frames on|off         Frame extraction (default: on)"
    echo "  --output-dir PATH       Output directory (default: ./output)"
    echo "  --config PATH           Custom config YAML"
    echo "  --model NAME            Override LLM model name"
    echo "  --verbose               Enable DEBUG logging"
    echo ""
    echo "Examples:"
    echo "  ./run.sh 'https://www.youtube.com/watch?v=VIDEO_ID'"
    echo "  ./run.sh 'https://youtu.be/VIDEO_ID' --detail low --frames off"
    echo "  ./run.sh 'https://www.youtube.com/watch?v=VIDEO_ID' --output-dir ./notes --verbose"
    echo ""
    echo "Quick check:  ./run.sh --check"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ---- Handle --check ----
if [[ "$1" == "--check" ]]; then
    echo -e "${BOLD}Running dependency check...${NC}"
    $PYTHON -m insightforge.cli check
    exit $?
fi

URL="$1"
shift

echo -e "${BOLD}InsightForge${NC} processing: ${CYAN}${URL}${NC}"
echo ""

# Run the pipeline, passing any remaining arguments through
$PYTHON -m insightforge.cli process "$URL" "$@"

echo ""
echo -e "${GREEN}${BOLD}Complete!${NC} Check the output directory for notes.md, transcript.txt, and frames/"
