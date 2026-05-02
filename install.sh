#!/bin/bash
# Auger Platform Installer
# Installs Auger and ensures PATH is configured

set -e

echo "🚀 Installing Auger Platform..."
echo ""

# Ensure ~/.local/bin is in PATH
BASHRC="$HOME/.bashrc"
LOCAL_BIN="$HOME/.local/bin"
PATH_EXPORT='export PATH="$HOME/.local/bin:$PATH"'

# Check if already in PATH
if ! echo "$PATH" | grep -q "$LOCAL_BIN"; then
    echo "📝 Adding ~/.local/bin to PATH in $BASHRC"
    
    # Check if already in .bashrc
    if ! grep -q 'export PATH="$HOME/.local/bin:$PATH"' "$BASHRC" 2>/dev/null; then
        echo "" >> "$BASHRC"
        echo "# Added by Auger Platform installer" >> "$BASHRC"
        echo "$PATH_EXPORT" >> "$BASHRC"
        echo "✅ Added to $BASHRC"
    else
        echo "✅ Already in $BASHRC"
    fi
    
    # Export for current session
    export PATH="$LOCAL_BIN:$PATH"
    echo "✅ Added to current session"
else
    echo "✅ ~/.local/bin already in PATH"
fi

echo ""
echo "📦 Installing Python package..."

# Use regular install in test mode, editable for development
if [ "${TEST_MODE}" = "true" ]; then
    echo "Test mode: Using regular install"
    pip install --user .
else
    pip install --user -e .
fi

echo ""
echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Reload your shell: source ~/.bashrc"
echo "  2. Initialize Auger: auger init --token YOUR_GITHUB_COPILOT_TOKEN"
echo "  3. Start the platform: auger start"
echo ""
echo "Get your token at: https://github.com/settings/tokens"
echo ""
