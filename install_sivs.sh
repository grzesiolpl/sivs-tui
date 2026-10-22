#!/bin/bash
# install_sivs.sh - Install SIVS globally on macOS
# Run: bash install_sivs.sh

set -e

SIVS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/usr/local/bin"
SIVS_COMMAND="$SIVS_DIR/SIVS.command"

echo "🎬 Installing SIVS globally..."

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "❌ This installer is for macOS only."
    exit 1
fi

# Check if SIVS directory exists
if [ ! -d "$SIVS_DIR" ]; then
    echo "❌ SIVS directory not found: $SIVS_DIR"
    exit 1
fi

# Make command executable
chmod +x "$SIVS_COMMAND"

# Create global symlink
if [ -L "$INSTALL_DIR/sivs" ]; then
    echo "🔄 Updating existing symlink..."
    rm "$INSTALL_DIR/sivs"
fi

ln -sf "$SIVS_DIR/sivs" "$INSTALL_DIR/sivs"
echo "✅ Created global command: sivs"

# Also create symlink for the .command file for Finder integration
if [ -L "$HOME/Desktop/SIVS.command" ]; then
    rm "$HOME/Desktop/SIVS.command"
fi

ln -sf "$SIVS_DIR/SIVS.command" "$HOME/Desktop/SIVS.command"
echo "✅ Created Desktop shortcut: SIVS.command"

# Create .config/sivs directory if it doesn't exist
mkdir -p "$HOME/.config/sivs"

# Create default .env if it doesn't exist
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
    echo "✅ Created config: ~/.config/sivs/.env"
    echo "⚠️  Edit ~/.config/sivs/.env and add your OPENROUTER_API_KEY"
else
    echo "ℹ️  Config already exists: ~/.config/sivs/.env"
fi

echo ""
echo "🎉 Installation complete!"
echo ""
echo "Usage:"
echo "  sivs                    # Start TUI, select file in UI"
echo "  sivs video.mp4         # Open video.mp4 directly"
echo "  sivs --doctor          # Check system dependencies"
echo "  sivs --config          # Show configuration"
echo ""
echo "Or double-click SIVS.command on Desktop or in Finder"
echo ""
echo "⚠️  Remember to add your OPENROUTER_API_KEY to ~/.config/sivs/.env"