#!/usr/bin/env bash
# InsightForge — browse and view processed video notes.
#
# Usage:
#   ./view.sh                     # interactive picker, default output dir
#   ./view.sh --dir ./my-output   # use a custom output directory
#   ./view.sh --glow              # force terminal viewer (glow)
#   ./view.sh --obsidian          # force Obsidian
#   ./view.sh --html              # open HTML viewer directly
#   ./view.sh --notes-html        # open notes-only HTML page
#   ./view.sh --host-html         # serve HTML viewer over localhost
#   ./view.sh <folder_name>       # open a specific output directly
#
set -euo pipefail

# ---- Colour helpers ----
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ---- Defaults ----
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/output"
VIEWER=""        # auto-detect
DIRECT_FOLDER="" # if user passes a folder name directly

# ---- Find Python ----
if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3.11 &>/dev/null; then
    PYTHON=python3.11
elif command -v python3 &>/dev/null; then
    PYTHON=python3
else
    echo -e "${RED}Python 3 not found.${NC}"
    exit 1
fi

# ---- Parse arguments ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --glow)
            VIEWER="glow"
            shift
            ;;
        --obsidian)
            VIEWER="obsidian"
            shift
            ;;
        --html)
            VIEWER="html"
            shift
            ;;
        --notes-html)
            VIEWER="notes-html"
            shift
            ;;
        --host-html)
            VIEWER="html-host"
            shift
            ;;
        --help|-h)
            echo -e "${BOLD}InsightForge Viewer${NC}"
            echo ""
            echo -e "Usage: ${CYAN}./view.sh [options] [folder_name]${NC}"
            echo ""
            echo "Options:"
            echo "  --dir PATH       Output directory to browse (default: ./output)"
            echo "  --glow           Use glow (terminal Markdown viewer)"
            echo "  --obsidian       Use Obsidian (GUI Markdown editor)"
            echo "  --html           Open viewer/index.html if available"
            echo "  --notes-html     Open viewer/notes.html if available"
            echo "  --host-html      Serve viewer/index.html on localhost and open it"
            echo "  -h, --help       Show this help"
            echo ""
            echo "If no viewer is specified, you'll be prompted to choose."
            exit 0
            ;;
        -*)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
        *)
            DIRECT_FOLDER="$1"
            shift
            ;;
    esac
done

# ---- Resolve output directory ----
if [[ ! -d "$OUTPUT_DIR" ]]; then
    echo -e "${RED}Output directory not found: ${OUTPUT_DIR}${NC}"
    echo -e "Run ${CYAN}./run.sh <youtube_url>${NC} first to process a video."
    exit 1
fi

# ---- Gather available outputs ----
# Each output is a subdirectory containing notes.md
OUTPUTS=()
TITLES=()
while IFS= read -r notes_file; do
    dir="$(dirname "$notes_file")"
    folder="$(basename "$dir")"
    # Read title from first line of notes.md (strip "# " prefix)
    title=$(head -1 "$notes_file" | sed 's/^# //')
    OUTPUTS+=("$dir")
    TITLES+=("$title")
done < <(find "$OUTPUT_DIR" -maxdepth 2 -name "notes.md" -type f 2>/dev/null | sort)

if [[ ${#OUTPUTS[@]} -eq 0 ]]; then
    echo -e "${RED}No processed videos found in ${OUTPUT_DIR}${NC}"
    echo -e "Run ${CYAN}./run.sh <youtube_url>${NC} first to process a video."
    exit 1
fi

# ---- If user specified a folder name directly, find it ----
if [[ -n "$DIRECT_FOLDER" ]]; then
    FOUND=""
    for i in "${!OUTPUTS[@]}"; do
        if [[ "$(basename "${OUTPUTS[$i]}")" == *"$DIRECT_FOLDER"* ]]; then
            FOUND="${OUTPUTS[$i]}"
            break
        fi
    done
    if [[ -z "$FOUND" ]]; then
        echo -e "${RED}No output matching '${DIRECT_FOLDER}' found.${NC}"
        echo ""
        echo "Available outputs:"
        for i in "${!OUTPUTS[@]}"; do
            echo "  $(basename "${OUTPUTS[$i]}")"
        done
        exit 1
    fi
    SELECTED="$FOUND"
else
    # ---- Interactive picker ----
    echo -e "${BOLD}InsightForge — Processed Videos${NC}"
    echo ""

    for i in "${!OUTPUTS[@]}"; do
        dir="${OUTPUTS[$i]}"
        title="${TITLES[$i]}"
        folder="$(basename "$dir")"

        # Gather stats
        frame_count=0
        if [[ -d "$dir/frames" ]]; then
            frame_count=$(find "$dir/frames" -maxdepth 1 -name "*.jpg" -type f 2>/dev/null | wc -l | tr -d ' ')
        fi
        has_transcript="no"
        [[ -f "$dir/transcript.txt" ]] && has_transcript="yes"
        has_html="no"
        [[ -f "$dir/viewer/index.html" ]] && has_html="yes"

        # Display
        num=$((i + 1))
        echo -e "  ${BOLD}${num}.${NC} ${GREEN}${title}${NC}"
        echo -e "     ${DIM}${folder}${NC}"
        echo -e "     ${DIM}Frames: ${frame_count} | Transcript: ${has_transcript} | HTML: ${has_html}${NC}"
        echo ""
    done

    # Prompt for selection
    echo -ne "${CYAN}Select a video [1-${#OUTPUTS[@]}]: ${NC}"
    read -r choice

    if ! [[ "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#OUTPUTS[@]} )); then
        echo -e "${RED}Invalid selection.${NC}"
        exit 1
    fi

    SELECTED="${OUTPUTS[$((choice - 1))]}"
fi

SELECTED_TITLE=$(head -1 "$SELECTED/notes.md" | sed 's/^# //')
echo ""
echo -e "${BOLD}Selected:${NC} ${GREEN}${SELECTED_TITLE}${NC}"

# ---- Show output summary ----
echo ""
echo -e "${BOLD}Contents:${NC}"
for f in notes.md transcript.txt metadata.json; do
    if [[ -f "$SELECTED/$f" ]]; then
        size=$(wc -c < "$SELECTED/$f" | tr -d ' ')
        echo -e "  ${GREEN}✓${NC} $f  ${DIM}(${size} bytes)${NC}"
    fi
done
if [[ -f "$SELECTED/viewer/index.html" ]]; then
    echo -e "  ${GREEN}✓${NC} viewer/index.html  ${DIM}(interactive HTML viewer)${NC}"
fi
if [[ -f "$SELECTED/viewer/notes.html" ]]; then
    echo -e "  ${GREEN}✓${NC} viewer/notes.html  ${DIM}(notes-only HTML page)${NC}"
fi
if [[ -d "$SELECTED/frames" ]]; then
    fc=$(find "$SELECTED/frames" -maxdepth 1 -name "*.jpg" -type f 2>/dev/null | wc -l | tr -d ' ')
    echo -e "  ${GREEN}✓${NC} frames/  ${DIM}(${fc} images)${NC}"
fi
echo ""

# ---- Choose viewer ----
if [[ -z "$VIEWER" ]]; then
    echo -e "${BOLD}How would you like to view?${NC}"
    echo ""
    echo "  1. glow       (terminal — Markdown only)"
    echo "  2. obsidian   (GUI — Markdown + images)"
    echo "  3. transcript (terminal — full transcript via glow)"
    echo "  4. html       (open interactive HTML viewer)"
    echo "  5. notes-html (open notes-only HTML page)"
    echo "  6. host-html  (serve HTML viewer on localhost)"
    echo "  7. open       (open folder in Finder)"
    echo ""
    echo -ne "${CYAN}Choose [1-7]: ${NC}"
    read -r vchoice

    case "$vchoice" in
        1) VIEWER="glow" ;;
        2) VIEWER="obsidian" ;;
        3) VIEWER="transcript" ;;
        4) VIEWER="html" ;;
        5) VIEWER="notes-html" ;;
        6) VIEWER="html-host" ;;
        7) VIEWER="open" ;;
        *)
            echo -e "${RED}Invalid choice.${NC}"
            exit 1
            ;;
    esac
fi

# ---- Launch viewer ----
case "$VIEWER" in
    glow)
        if ! command -v glow &>/dev/null; then
            echo -e "${RED}glow not found. Install with: brew install glow${NC}"
            exit 1
        fi
        echo -e "${DIM}Launching glow...${NC}"
        glow "$SELECTED/notes.md"
        ;;
    obsidian)
        if [[ ! -d "/Applications/Obsidian.app" ]]; then
            echo -e "${RED}Obsidian not found. Install with: brew install --cask obsidian${NC}"
            exit 1
        fi
        # Use each video's output folder as its own vault — keeps it self-contained
        VAULT_DIR="$(cd "$SELECTED" && pwd)"
        if [[ ! -d "$VAULT_DIR/.obsidian" ]]; then
            mkdir -p "$VAULT_DIR/.obsidian"
        fi

        # Register vault in Obsidian's config so the URI works
        OBSIDIAN_CONFIG="$HOME/Library/Application Support/obsidian/obsidian.json"
        if [[ -f "$OBSIDIAN_CONFIG" ]]; then
            "$PYTHON" -c "
import json, sys, hashlib, time
cfg_path, vault_path = sys.argv[1], sys.argv[2]
with open(cfg_path) as f:
    cfg = json.load(f)
for v in cfg.get('vaults', {}).values():
    if v.get('path') == vault_path:
        sys.exit(0)
vid = hashlib.md5(vault_path.encode()).hexdigest()[:16]
cfg.setdefault('vaults', {})[vid] = {'path': vault_path, 'ts': int(time.time() * 1000)}
with open(cfg_path, 'w') as f:
    json.dump(cfg, f)
" "$OBSIDIAN_CONFIG" "$VAULT_DIR" 2>/dev/null || true
        fi

        VAULT_NAME="$(basename "$VAULT_DIR")"
        echo -e "${DIM}Opening in Obsidian (vault: ${VAULT_NAME})...${NC}"
        # Open Obsidian with the vault path directly — works even for new vaults
        open -a Obsidian "$VAULT_DIR"
        ;;
    transcript)
        if [[ ! -f "$SELECTED/transcript.txt" ]]; then
            echo -e "${RED}No transcript.txt found for this video.${NC}"
            exit 1
        fi
        if command -v glow &>/dev/null; then
            glow "$SELECTED/transcript.txt"
        else
            cat "$SELECTED/transcript.txt"
        fi
        ;;
    html)
        if [[ ! -f "$SELECTED/viewer/index.html" ]]; then
            echo -e "${RED}No HTML viewer found for this video.${NC}"
            echo -e "Re-run with ${CYAN}./run.sh '<youtube_url>' --html on${NC}"
            exit 1
        fi
        echo -e "${DIM}Opening HTML viewer...${NC}"
        open "$SELECTED/viewer/index.html"
        ;;
    notes-html)
        if [[ ! -f "$SELECTED/viewer/notes.html" ]]; then
            echo -e "${RED}No notes HTML page found for this video.${NC}"
            echo -e "Re-run with ${CYAN}./run.sh '<youtube_url>' --html on${NC}"
            exit 1
        fi
        echo -e "${DIM}Opening notes HTML page...${NC}"
        open "$SELECTED/viewer/notes.html"
        ;;
    html-host)
        if [[ ! -f "$SELECTED/viewer/index.html" ]]; then
            echo -e "${RED}No HTML viewer found for this video.${NC}"
            echo -e "Re-run with ${CYAN}./run.sh '<youtube_url>' --html on${NC}"
            exit 1
        fi
        PORT=8765
        VIEWER_URL="http://127.0.0.1:${PORT}/$(basename "$SELECTED")/viewer/index.html"
        echo -e "${DIM}Serving ${OUTPUT_DIR} on ${VIEWER_URL}${NC}"
        echo -e "${DIM}Press Ctrl+C to stop the local server.${NC}"
        if command -v open &>/dev/null; then
            open "$VIEWER_URL" >/dev/null 2>&1 || true
        fi
        (
            cd "$SCRIPT_DIR"
            "$PYTHON" -m insightforge.viewer_server --root "$OUTPUT_DIR" --port "$PORT"
        )
        ;;
    open)
        echo -e "${DIM}Opening in Finder...${NC}"
        open "$SELECTED"
        ;;
esac
