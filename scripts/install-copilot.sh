#!/bin/bash
# Install standalone GitHub Copilot CLI
# This is required for Ask Genny to function

set -e

echo "[PKG] Installing GitHub Copilot CLI..."
echo ""

USER_BIN="$HOME/.local/bin"
mkdir -p "$USER_BIN"

# Download and install copilot CLI
curl -fsSL https://gh.io/copilot-install | bash

# Check if installation was successful
if [ -f "$USER_BIN/copilot" ]; then
    echo ""
    echo "[OK] Copilot CLI installed at $USER_BIN/copilot"
    echo ""
    
    # Check if PATH is already set
    if echo "$PATH" | grep -q "$USER_BIN"; then
        echo "[OK] $USER_BIN is already in PATH"
    else
        echo "[WARN]  $USER_BIN is not in your PATH"
        echo ""
        echo "Add this line to ~/.bashrc (or ~/.zshrc for zsh):"
        echo ""
        echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        echo ""
        echo "Then run: source ~/.bashrc"
        echo ""
        echo "Or for immediate use in this terminal:"
        echo "  export PATH=\"$USER_BIN:\$PATH\""
    fi
else
    echo "[ERROR] Installation failed — copilot not found at $USER_BIN/copilot"
    exit 1
fi
