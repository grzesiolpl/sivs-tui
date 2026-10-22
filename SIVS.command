#!/bin/bash
# SIVS.command - macOS launcher for SIVS TUI
# Double-click this file to launch SIVS in Terminal

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Change to the SIVS project directory
cd "$SCRIPT_DIR"

# Check if virtual environment exists
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Run SIVS TUI
# If an argument was passed (e.g., drag & drop a file), pass it through
if [ $# -gt 0 ]; then
    python -m sivs_tui "$@"
else
    python -m sivs_tui
fi

# Keep terminal open on error
if [ $? -ne 0 ]; then
    echo ""
    echo "SIVS exited with an error. Press Enter to close..."
    read
fi