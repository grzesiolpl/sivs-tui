#!/bin/bash
# install_sivs.sh - Idiot-proof SIVS installer for macOS
# Run: bash install_sivs.sh
# Does: Homebrew → System deps → Python deps → SIVS package → Verify

set -e

SIVS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/usr/local/bin"
SIVS_COMMAND="$SIVS_DIR/SIVS.command"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() { echo -e "${BLUE}==>${NC} $1"; }
ok() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
err() { echo -e "${RED}❌${NC} $1"; }

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║          SIVS - Super Intelligence Video Studio              ║"
echo "║          Idiot-proof installer for macOS                     ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# ────────────────────────────────────────────────────────────────
# 1. CHECK macOS
# ────────────────────────────────────────────────────────────────
log "Checking platform..."
if [[ "$OSTYPE" != "darwin"* ]]; then
    err "This installer is for macOS only."
    exit 1
fi
ok "macOS detected"

# ────────────────────────────────────────────────────────────────
# 2. HOMEBREW
# ────────────────────────────────────────────────────────────────
log "Checking Homebrew..."
if ! command -v brew &> /dev/null; then
    warn "Homebrew not found. Installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    
    # Add to PATH for Apple Silicon
    if [[ -f "/opt/homebrew/bin/brew" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -f "/usr/local/bin/brew" ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
    ok "Homebrew installed"
else
    ok "Homebrew found: $(brew --version | head -1)"
fi

# ────────────────────────────────────────────────────────────────
# 3. SYSTEM DEPENDENCIES
# ────────────────────────────────────────────────────────────────
log "Installing system dependencies (ffmpeg, mpv, whisper-cpp)..."

DEPS=("ffmpeg" "mpv" "whisper-cpp")
MISSING=()

for dep in "${DEPS[@]}"; do
    if brew list "$dep" &> /dev/null; then
        ok "$dep already installed"
    else
        MISSING+=("$dep")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    log "Installing missing: ${MISSING[*]}"
    brew install "${MISSING[@]}"
    ok "System dependencies installed"
else
    ok "All system dependencies present"
fi

# ────────────────────────────────────────────────────────────────
# 4. PYTHON & PIP
# ────────────────────────────────────────────────────────────────
log "Checking Python..."

if ! command -v python3 &> /dev/null; then
    warn "Python3 not found. Installing via Homebrew..."
    brew install python@3.12
    ok "Python installed"
else
    PY_VER=$(python3 --version)
    ok "Python found: $PY_VER"
fi

# Ensure pip
if ! command -v pip3 &> /dev/null; then
    warn "pip3 not found. Installing..."
    python3 -m ensurepip --upgrade
fi

# ────────────────────────────────────────────────────────────────
# 5. PYTHON DEPENDENCIES
# ────────────────────────────────────────────────────────────────
log "Installing Python dependencies (kinocut, cutagent, textual, rich)..."

# Use virtual environment to avoid PEP 668 (externally-managed-environment)
VENV_DIR="$SIVS_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Upgrade pip in venv
"$VENV_DIR/bin/pip" install --upgrade pip --quiet

# Install required packages in venv
PY_DEPS=(
    "kinocut"
    "cutagent[ffmpeg]"
    "textual"
    "rich"
    "pydantic"
    "pydantic-settings"
    "openai"  # for OpenRouter API
)

for dep in "${PY_DEPS[@]}"; do
    if "$VENV_DIR/bin/python" -c "import ${dep%%[*]]}" &> /dev/null; then
        ok "$dep already installed"
    else
        log "Installing $dep..."
        "$VENV_DIR/bin/pip" install "$dep" --quiet
        ok "$dep installed"
    fi
done

# ────────────────────────────────────────────────────────────────
# 6. INSTALL SIVS PACKAGE (editable mode in venv)
# ────────────────────────────────────────────────────────────────
log "Installing SIVS package..."

cd "$SIVS_DIR"

# Make sure sivs entry point is executable
chmod +x "$SIVS_COMMAND"
chmod +x "$SIVS_DIR/sivs"

# Install in editable mode in venv
"$VENV_DIR/bin/pip" install -e . --quiet
ok "SIVS package installed in venv"

# ────────────────────────────────────────────────────────────────
# 7. CREATE GLOBAL SYMLINKS
# ────────────────────────────────────────────────────────────────
log "Creating global commands..."

# Main sivs command
if [ -L "$INSTALL_DIR/sivs" ]; then
    rm "$INSTALL_DIR/sivs"
fi
ln -sf "$SIVS_DIR/sivs" "$INSTALL_DIR/sivs"
ok "Global command: sivs"

# Desktop shortcut
if [ -L "$HOME/Desktop/SIVS.command" ]; then
    rm "$HOME/Desktop/SIVS.command"
fi
ln -sf "$SIVS_COMMAND" "$HOME/Desktop/SIVS.command"
ok "Desktop shortcut: SIVS.command"

# ────────────────────────────────────────────────────────────────
# 8. CONFIGURATION
# ────────────────────────────────────────────────────────────────
log "Setting up configuration..."

mkdir -p "$HOME/.config/sivs"

if [ ! -f "$HOME/.config/sivs/.env" ]; then
    cat > "$HOME/.config/sivs/.env" << 'EOF'
# SIVS Configuration
# Get your API key from https://openrouter.ai/keys
OPENROUTER_API_KEY=your_api_key_here

# Optional: Custom paths (auto-detected if not set)
# FFMPEG_PATH=/opt/homebrew/bin/ffmpeg
# FFPROBE_PATH=/opt/homebrew/bin/ffprobe
# MPV_PATH=/opt/homebrew/bin/mpv
# FFPLAY_PATH=/opt/homebrew/bin/ffplay
EOF
    ok "Config created: ~/.config/sivs/.env"
    warn "Edit ~/.config/sivs/.env and add your OPENROUTER_API_KEY"
else
    ok "Config exists: ~/.config/sivs/.env"
fi

# ────────────────────────────────────────────────────────────────
# 9. VERIFICATION (THE PRE-CHECK)
# ────────────────────────────────────────────────────────────────
echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                    VERIFICATION CHECK                          ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

log "Running sivs --doctor to verify installation..."

# Run doctor check using the wrapper (which uses venv)
if "$SIVS_DIR/sivs" --doctor; then
    echo ""
    ok "All checks passed!"
    VERIFIED=true
else
    echo ""
    warn "Some checks failed (see above). SIVS may still work with fallbacks."
    VERIFIED=false
fi

# ────────────────────────────────────────────────────────────────
# 10. FINAL SUMMARY
# ────────────────────────────────────────────────────────────────
echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                    INSTALLATION COMPLETE                       ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

if [ "$VERIFIED" = true ]; then
    echo -e "${GREEN}✅ SIVS is ready to use!${NC}"
else
    echo -e "${YELLOW}⚠️  SIVS installed but some dependencies missing.${NC}"
    echo "Run 'sivs --doctor' to see details."
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "NEXT STEPS:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  1️⃣  ADD API KEY (required for AI features):"
echo "      nano ~/.config/sivs/.env"
echo "      # Paste your key from https://openrouter.ai/keys"
echo ""
echo "  2️⃣  FIRST-TIME SETUP WIZARD (recommended):"
echo "      sivs --setup"
echo "      # Checks deps, sets API key, picks model, sets workspace"
echo ""
echo "  3️⃣  VERIFY AGAIN:"
echo "      sivs --doctor"
echo ""
echo "  4️⃣  START EDITING:"
echo "      sivs your_video.mp4"
echo "      # Or drag & drop video onto SIVS.command on Desktop"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "COMMANDS:"
echo "  sivs              # Start TUI"
echo "  sivs video.mp4    # Open file directly"
echo "  sivs --setup      # Interactive wizard"
echo "  sivs --doctor     # System check"
echo "  sivs --help       # Full guide"
echo "  sivs --web        # Launch Web UI (Next.js)"
echo "━━━━━━━┐═══════════════════════════════════════════════════════"
echo ""
echo "📁 Config: ~/.config/sivs/.env"
echo "🖥️  Desktop: ~/Desktop/SIVS.command (double-click to launch)"
echo "🌐 Repos:   TUI: github.com/grzesiolpl/sivs-tui"
echo "            Web: github.com/grzesiolpl/sivs"
echo ""