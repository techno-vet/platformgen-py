# Auger Ask - Quick Copilot Access

Quick reference for asking GitHub Copilot questions from Auger.

## Usage (Now Even Simpler!)

### Default Behavior - Just `auger`

```bash
# With prompt (ask mode)
auger "how do I deploy to kubernetes?"

# No prompt (GUI mode)
auger
```

**That's it!** No subcommands needed for quick questions.

### Legacy Methods (Still Work)

```bash
# Standalone command (after install-utilities.sh)
auger-ask "question"
auger-ask  # GUI

# From Auger GUI
# Use the "Ask Auger" panel
```

## Usage Examples

### Quick Terminal Questions

```bash
# DevOps tasks
auger "how do I check pod status in kubernetes?"
auger "create a Dockerfile for Python FastAPI app"

# Git operations
auger "how do I revert last commit?"
auger "squash last 3 commits"

# Debugging
auger "what does this error mean: ModuleNotFoundError"
auger "how to debug Python memory leak?"
```

### GUI Mode

Best for:
- Longer, multi-line prompts
- Copy-pasting error messages
- Complex questions

```bash
# Opens GUI window
auger
```

In GUI:
- Type your question (multi-line supported)
- Press **Ctrl+Enter** or click **Ask**
- Response appears in terminal

## Features

### Command Line Mode
- ✅ Quick one-liners
- ✅ Shell history saved
- ✅ Pipe-friendly
- ✅ Can chain with other commands

### GUI Mode
- ✅ Multi-line input
- ✅ Easy copy-paste
- ✅ No quote escaping needed
- ✅ Ctrl+Enter shortcut

## Requirements

Both commands require:

1. **GitHub CLI** (`gh`)
   ```bash
   # Install
   # See: https://cli.github.com/
   ```

2. **Copilot Extension**
   ```bash
   # Install
   gh extension install github/gh-copilot
   
   # Verify
   gh copilot --version
   ```

## Tips & Tricks

### Be Specific

❌ Bad:
```bash
auger ask "deploy app"
```

✅ Good:
```bash
auger ask "create kubernetes deployment yaml for nginx with 3 replicas"
```

### Include Context

```bash
auger ask "how to fix 'permission denied' when running docker? I'm on Ubuntu 22.04"
```

### Use for Code Review

```bash
auger ask "review this Python function: $(cat my_function.py)"
```

### Quick Scripts

```bash
auger ask "write bash script to backup PostgreSQL database"
```

### Error Help

```bash
# Copy error and ask
auger ask "$(kubectl logs pod-name 2>&1 | tail -20)"
```

## Keyboard Shortcuts

### GUI Mode
- **Ctrl+Enter** - Submit prompt
- **Escape** - Close window (when not focused on text)

### Terminal
- **Up Arrow** - Previous command
- **Ctrl+C** - Cancel

## Comparison

| Feature | `auger` | `auger-ask` | GUI Panel |
|---------|---------|-------------|-----------|
| Quick ask | ✅ | ✅ | ❌ |
| CLI commands | ✅ | ❌ | ❌ |
| GUI option | ✅ | ✅ | ✅ |
| Standalone | ❌ | ✅ | ❌ |
| Context aware | ❌ | ❌ | ✅ |

**Recommended**: Use `auger` for everything - it's dual-mode!

## Troubleshooting

### "gh: command not found"

Install GitHub CLI:
```bash
# Ubuntu/Debian
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install gh
```

### "extension not installed"

```bash
gh extension install github/gh-copilot
```

### "authentication required"

```bash
gh auth login
```

### GUI won't open

```bash
# Check DISPLAY
echo $DISPLAY

# If empty
export DISPLAY=:0

# Try again
auger ask
```

## Advanced Usage

### Scripting

```bash
#!/bin/bash
# Auto-ask on error

command_that_might_fail || {
    ERROR_MSG="$?"
    auger ask "how to fix exit code $ERROR_MSG in bash script?"
}
```

### Aliases

Add to `~/.bashrc`:
```bash
# Auger is already short, but you could make aliases:
alias ask='auger'
alias a='auger'

# Then use:
ask "quick question"
a "even quicker"
```

### Integration with Other Tools

```bash
# Ask about git diff
git diff | auger "review these changes"

# Ask about logs
docker logs container 2>&1 | tail -50 | auger "what's wrong?"

# Ask about system
df -h | auger "disk usage recommendations"
```

## FAQ

**Q: Can I still use platform commands?**

A: Yes! `auger init`, `auger start`, etc. all work. If first arg is a known command or starts with `--`, it uses CLI mode.

**Q: How does it know if I'm asking a question?**

A: If you don't provide a known subcommand (init, start, doctor, etc.) or a `--flag`, it assumes ask mode.

**Q: Does this cost money?**

A: Uses your GitHub Copilot subscription. No additional cost.

**Q: Can I customize the prompts?**

A: Yes, edit the scripts or create wrappers. Both are open source.

**Q: Is my data sent to GitHub?**

A: Yes, prompts are sent to GitHub Copilot API. Don't include secrets!

---

**Quick Start:**
```bash
auger ask "how do I get started with Auger?"
```
