#!/bin/bash
# Post-install script to set up additional Auger utilities

echo "[PKG] Setting up Auger utilities..."

# Install auger-ask to ~/.local/bin
INSTALL_DIR="$HOME/.local/bin"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$INSTALL_DIR"

# Copy auger-ask
if [ -f "$SCRIPT_DIR/auger-ask" ]; then
    cp "$SCRIPT_DIR/auger-ask" "$INSTALL_DIR/auger-ask"
    chmod +x "$INSTALL_DIR/auger-ask"
    echo "[OK] Installed auger-ask to $INSTALL_DIR/auger-ask"
else
    echo "[WARN]  Could not find auger-ask script"
fi

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
echo "  auger           - Main Auger Platform CLI"
echo "  auger ask       - Ask Copilot (integrated)"
echo "  auger-ask       - Ask Copilot (standalone)"
