# Ask Genny - Quick Copilot Access

Quick reference for asking GitHub Copilot questions from PlatformGen.

## Usage (Now Even Simpler!)

### Default Behavior - Just `genny`

```bash
# With prompt (ask mode)
genny "how do I deploy to kubernetes?"

# No prompt (GUI mode)
genny
```

**That's it!** No subcommands needed for quick questions.

### Legacy Methods (Still Work)

```bash
# Standalone command (after install-utilities.sh)
auger-ask "question"
auger-ask  # GUI

# From PlatformGen GUI
# Use the "Ask Genny" panel
```

## Usage Examples

### Quick Terminal Questions

```bash
# DevOps tasks
genny "how do I check pod status in kubernetes?"
genny "create a Dockerfile for Python FastAPI app"

# Git operations
genny "how do I revert last commit?"
genny "squash last 3 commits"

# Debugging
genny "what does this error mean: ModuleNotFoundError"
genny "how to debug Python memory leak?"
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
genny ask "deploy app"
```

✅ Good:
```bash
genny ask "create kubernetes deployment yaml for nginx with 3 replicas"
```

### Include Context

```bash
genny ask "how to fix 'permission denied' when running docker? I'm on Ubuntu 22.04"
```

### Use for Code Review

```bash
genny ask "review this Python function: $(cat my_function.py)"
```

### Quick Scripts

```bash
genny ask "write bash script to backup PostgreSQL database"
```

### Error Help

```bash
# Copy error and ask
genny ask "$(kubectl logs pod-name 2>&1 | tail -20)"
```

## Keyboard Shortcuts

### GUI Mode
- **Ctrl+Enter** - Submit prompt
- **Escape** - Close window (when not focused on text)

### Terminal
- **Up Arrow** - Previous command
- **Ctrl+C** - Cancel

## Comparison

| Feature | `genny` | `auger-ask` | GUI Panel |
|---------|---------|-------------|-----------|
| Quick ask | ✅ | ✅ | ❌ |
| CLI commands | ✅ | ❌ | ❌ |
| GUI option | ✅ | ✅ | ✅ |
| Standalone | ❌ | ✅ | ❌ |
| Context aware | ❌ | ❌ | ✅ |

**Recommended**: Use `genny` for quick questions and the Ask Genny panel for rich in-app context.

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
genny ask
```

## Advanced Usage

### Scripting

```bash
#!/bin/bash
# Auto-ask on error

command_that_might_fail || {
    ERROR_MSG="$?"
    genny ask "how to fix exit code $ERROR_MSG in bash script?"
}
```

### Aliases

Add to `~/.bashrc`:
```bash
# Genny is already short, but you could make aliases:
alias ask='genny'
alias a='genny'

# Then use:
ask "quick question"
a "even quicker"
```

### Integration with Other Tools

```bash
# Ask about git diff
git diff | genny "review these changes"

# Ask about logs
docker logs container 2>&1 | tail -50 | genny "what's wrong?"

# Ask about system
df -h | genny "disk usage recommendations"
```

## FAQ

**Q: Can I still use platform commands?**

A: Yes. `platformgen`, `genny`, and the legacy `auger` wrapper all work. If the first arg is a known subcommand or starts with `--`, it uses CLI mode.

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
genny ask "how do I get started with PlatformGen?"
```
