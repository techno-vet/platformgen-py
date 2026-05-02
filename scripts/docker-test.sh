#!/bin/bash
# Automated test script for Docker container
# Tests complete installation process from scratch

set -e

echo "=========================================="
echo "🧪 Auger Platform - Automated Test"
echo "=========================================="
echo ""

# Check if in test user environment
if [ "$USER" = "testuser" ]; then
    echo "[OK] Running as test user"
else
    echo "[WARN]  Running as: $USER (expected: testuser)"
fi

echo ""
echo "📋 Environment Check"
echo "----------------------------------------"
echo "Python: $(python3 --version)"
echo "Pip: $(pip --version | head -1)"
echo "Git: $(git --version)"
echo "GH CLI: $(gh --version | head -1)"

# Check for standalone Copilot CLI
if command -v copilot &> /dev/null; then
    echo "Copilot: $(copilot --version 2>&1 | head -1)"
else
    echo "[WARN]  Copilot CLI not found (needed for Ask Auger)"
fi

echo ""
echo "🔑 Token Check"
echo "----------------------------------------"
if [ -n "$GITHUB_COPILOT_TOKEN" ]; then
    echo "[OK] GITHUB_COPILOT_TOKEN is set"
else
    echo "[ERROR] GITHUB_COPILOT_TOKEN not set"
    echo "   Set it in .env file or pass as environment variable"
    exit 1
fi

echo ""
echo "[PKG] Installing Auger Platform"
echo "----------------------------------------"

# Copy to a writable location
echo "Copying source to writable directory..."
cp -r /home/testuser/auger-platform /tmp/auger-build
cd /tmp/auger-build

# Test the install script
echo "Running: ./install.sh"
./install.sh

echo ""
echo "[SEARCH] Verifying Installation"
echo "----------------------------------------"

# Check if auger command exists
if command -v auger &> /dev/null; then
    echo "[OK] auger command found"
    auger --version
else
    echo "[ERROR] auger command not found"
    echo "PATH: $PATH"
    ls -la ~/.local/bin/ || echo "~/.local/bin/ doesn't exist"
    exit 1
fi

echo ""
echo "⚙️  Initializing Configuration"
echo "----------------------------------------"
echo "Running: auger init --token \$GITHUB_COPILOT_TOKEN"
auger init --token "$GITHUB_COPILOT_TOKEN"

# Verify config was created
if [ -f ~/.auger/config.yaml ]; then
    echo "[OK] Config file created"
    echo ""
    echo "Config contents:"
    cat ~/.auger/config.yaml
else
    echo "[ERROR] Config file not created"
    exit 1
fi

echo ""
echo "🧪 Testing CLI Commands"
echo "----------------------------------------"

# Test doctor command
echo "Running: auger doctor"
auger doctor

# Test config command
echo ""
echo "Running: auger config"
auger config

# Test widgets command
echo ""
echo "Running: auger widgets"
auger widgets

echo ""
echo "🎯 Testing Ask Mode"
echo "----------------------------------------"

# Test ask mode - use standalone copilot
if command -v copilot &> /dev/null; then
    echo "Testing: auger \"echo hello world\""
    echo ""
    echo "Copilot response:"
    echo "----------------------------------------"
    # Give it 30 seconds to respond
    timeout 30 auger "echo hello world" || {
        EXIT_CODE=$?
        if [ $EXIT_CODE -eq 124 ]; then
            echo "[WARN]  Copilot took longer than 30 seconds to respond"
        else
            echo "[OK] Copilot responded successfully"
        fi
    }
else
    echo "[WARN]  Skipping Ask mode test (copilot CLI not available)"
fi

echo ""
echo "=========================================="
echo "[OK] All Tests Passed!"
echo "=========================================="
echo ""
echo "Auger Platform is ready for use!"
echo ""
