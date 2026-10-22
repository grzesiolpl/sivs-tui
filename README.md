# SIVS-TUI - Super Intelligence Video Studio (Terminal UI)

A modern, keyboard-driven Terminal User Interface for video editing workflows. Built with Python, `textual`, and `rich`.

## Features

- **In-Place Editing**: Work directly in your video folder - no copying files
- **Zero-Render Live Preview**: 3 preview levels (ASCII timeline → mpv EDL → ffplay/QuickLook)
- **AI-Powered Plans**: Describe edits in natural language, get structured edit plans via LLM
- **Multi-Target Export**: FCPXML (Final Cut Pro), EDL (DaVinci/Audio), FCP7 XML (After Effects/Premiere), Universal
- **Keyboard-First**: Full Vim-style key bindings (P/B/E/R/T/O/Q)
- **macOS Native**: `.command` launcher, global `sivs` command, Finder integration

## Installation

```bash
# Clone and install
git clone https://github.com/grzesiolpl/sivs-tui.git
cd sivs-tui
bash install_sivs.sh
```

This creates:
- Global `sivs` command in `/usr/local/bin`
- `SIVS.command` on Desktop (double-click to launch)
- Config at `~/.config/sivs/.env`

**Important**: Add your OpenRouter API key to `~/.config/sivs/.env`:
```bash
echo "OPENROUTER_API_KEY=your_key_here" >> ~/.config/sivs/.env
```

## Usage

```bash
# Start TUI, select file in UI
sivs

# Open file directly
sivs video.mp4

# Check system dependencies
sivs --doctor

# Show configuration
sivs --config
```

## Workflow

1. **Load** - `sivs video.mp4` or drag file to TUI
2. **Brief** - Type natural language: *"Cut 0:10-0:20, slow-mo 0:30-0:35 at 0.33x"*
3. **Preview** - Press `P` for instant mpv EDL preview (0s render)
4. **Refine** - Press `B` to refine, `E` to edit JSON in $EDITOR
5. **Export** - Press `T` for FCPXML/EDL/XML, `R` for rendered MP4/MOV
6. **Deliver** - Press `O` to reveal in Finder

## Key Bindings

| Key | Action |
|-----|--------|
| `P` | ▶ Live Preview (mpv EDL / ffplay) |
| `B` | 💬 Refine Brief / AI Edit |
| `E` | ✏️ Edit Plan JSON ($EDITOR) |
| `R` | 🚀 Render Output |
| `T` | 🎞️ Export Timeline (XML/EDL) |
| `O` | 📂 Show in Finder |
| `Q` | ❌ Quit |

## Export Targets

| Target | Timeline Format | Render Format |
|--------|----------------|---------------|
| Final Cut Pro | `.fcpxml` | `.mov` (ProRes) |
| DaVinci Resolve | `.fcpxml` + `.edl` | `.mov` (ProRes/DNxHR) |
| After Effects / Premiere | `_fcp7.xml` | `.mov` (All-Intra H.264) |
| Audio DAW | `.edl` | `.wav` (24-bit 48kHz) |
| Universal / Social | `.fcpxml` + `.edl` | `.mp4` (H.264) |

## Architecture

```
sivs_tui/
├── app.py              # Main Textual TUI application
├── config.py           # Pydantic settings management
├── models.py           # Pydantic data models
├── cli.py              # CLI entry point
├── core/
│   └── analyzer.py     # ffprobe/ffmpeg media analysis
├── preview/
│   └── __init__.py     # 3-level preview system
├── exporters/
│   └── __init__.py     # FCPXML/EDL/FCP7 XML exporters
├── utils/
│   └── ai_brief.py     # LLM-powered plan generation
└── exporters/
    └── export_*.py     # Legacy CLI exporters (reused)
```

## Requirements

- Python 3.10+
- ffmpeg + ffprobe (via Homebrew: `brew install ffmpeg`)
- mpv (for instant preview: `brew install mpv`)
- OpenRouter API key (for AI features)

## Development

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .
mypy sivs_tui

# Run TUI in dev mode
python -m sivs_tui --dev
```

## License

MIT