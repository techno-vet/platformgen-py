#!/bin/bash
# Post-install script to set up additional PlatformGen utilities

echo "[PKG] Setting up PlatformGen utilities..."

# Install standalone ask helpers to ~/.local/bin
INSTALL_DIR="$HOME/.local/bin"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$INSTALL_DIR"

for script_name in ask-genny auger-ask; do
    if [ -f "$SCRIPT_DIR/$script_name" ]; then
        cp "$SCRIPT_DIR/$script_name" "$INSTALL_DIR/$script_name"
        chmod +x "$INSTALL_DIR/$script_name"
        echo "[OK] Installed $script_name to $INSTALL_DIR/$script_name"
    else
        echo "[WARN]  Could not find $script_name script"
    fi
done

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo ""
    echo "[WARN]  $HOME/.local/bin is not in your PATH"
    echo "   Add to your ~/.bashrc or ~/.bash_profile:"
    echo '   export PATH="$HOME/.local/bin:$PATH"'
fi

echo ""
echo "[OK] Setup complete!"
echo ""
echo "Available commands:"
echo "  platformgen     - Main PlatformGen CLI"
echo "  genny           - Main Genny CLI"
echo "  auger           - Legacy CLI compatibility alias"
echo "  auger ask       - Ask Copilot (integrated)"
echo "  ask-genny       - Ask Copilot (standalone)"
echo "  auger-ask       - Legacy standalone compatibility alias"
